"""Microsoft Graph client using per-tenant app registration credentials."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, AsyncIterator

import httpx
from azure.identity import ClientSecretCredential

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/.default"
USER_SELECT = (
    "id,displayName,mail,userPrincipalName,accountEnabled,jobTitle,department,usageLocation,assignedLicenses"
)

SP_SELECT = (
    "id,appId,displayName,servicePrincipalType,accountEnabled,appOwnerOrganizationId,"
    "homepage,tags,appRoles,appRoleAssignmentRequired,publisherName,signInAudience,notes,"
    "preferredSingleSignOnMode"
)
APP_REG_SELECT = "id,appId,displayName,signInAudience,publisherDomain,createdDateTime,notes,description"
ASSIGNMENT_SELECT = (
    "id,appRoleId,principalDisplayName,principalId,principalType,resourceDisplayName,resourceId,createdDateTime"
)


class GraphError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _nickname(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]", "", name)[:32] or "item"
    if slug[0].isdigit():
        slug = f"g{slug}"
    return slug.lower()


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
        err = body.get("error") or {}
        message = err.get("message") or response.text
        code = err.get("code")
        if code == "Authorization_RequestDenied" or "Insufficient privileges" in str(message):
            return (
                f"{code + ': ' if code else ''}{message} "
                "Grant application permissions User.ReadWrite.All, Group.ReadWrite.All and Directory.Read.All "
                "on this tenant's app registration, then grant admin consent."
            )
        if code:
            return f"{code}: {message}"
        return str(message)
    except Exception:
        return response.text[:2000] or f"Graph HTTP {response.status_code}"


class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id.strip()
        self.client_id = client_id.strip()
        self.client_secret = client_secret
        self._token: str | None = None
        self._token_expires = 0.0
        self._lock = asyncio.Lock()
        self.last_request_id: str | None = None

    @classmethod
    def from_tenant(cls, tenant: Any) -> "GraphClient":
        secret = ""
        if isinstance(getattr(tenant, "secrets", None), dict):
            secret = str(tenant.secrets.get("client_secret") or "")
        if not tenant.tenant_id or not tenant.client_id or not secret:
            raise GraphError(400, "This tenant is missing Graph credentials. Add tenant ID, client ID and client secret in Entra config.")
        return cls(str(tenant.tenant_id), str(tenant.client_id), secret)

    def configured(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret)

    def clear_token(self) -> None:
        self._token = None
        self._token_expires = 0.0

    async def _access_token(self) -> str:
        if not self.configured():
            raise GraphError(400, "This tenant is missing Graph credentials.")
        async with self._lock:
            if self._token and time.time() < self._token_expires - 60:
                return self._token

            def fetch() -> tuple[str, float]:
                try:
                    cred = ClientSecretCredential(self.tenant_id, self.client_id, self.client_secret)
                    result = cred.get_token(SCOPE)
                    return result.token, float(result.expires_on)
                except GraphError:
                    raise
                except Exception as exc:  # noqa: BLE001 — surface Azure identity failures as Graph errors
                    raise GraphError(401, str(exc)) from exc

            self._token, self._token_expires = await asyncio.to_thread(fetch)
            return self._token

    async def _send(
        self, method: str, url: str, token: str, json: Any | None, params: dict | None
    ) -> httpx.Response:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=json,
                params=params,
            )
        self.last_request_id = response.headers.get("request-id") or response.headers.get("client-request-id")
        return response

    async def request(self, method: str, path: str, *, json: Any | None = None, params: dict | None = None) -> Any:
        token = await self._access_token()
        url = path if path.startswith("http") else f"{GRAPH}{path}"
        response = await self._send(method, url, token, json, params)
        if response.status_code == 401:
            self.clear_token()
            token = await self._access_token()
            response = await self._send(method, url, token, json, params)
        if response.status_code >= 400:
            raise GraphError(response.status_code, _error_message(response))
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    async def paged(self, path: str, params: dict | None = None) -> AsyncIterator[dict[str, Any]]:
        url = path if path.startswith("http") else f"{GRAPH}{path}"
        query = params
        while url:
            data = await self.request("GET", url, params=query)
            query = None
            for item in data.get("value") or []:
                yield item
            url = data.get("@odata.nextLink")

    async def organization(self) -> dict[str, Any]:
        data = await self.request("GET", "/organization", params={"$select": "id,displayName,verifiedDomains"})
        rows = data.get("value") if isinstance(data, dict) else None
        if rows:
            return rows[0]
        return data if isinstance(data, dict) else {}

    async def list_users(self) -> list[dict[str, Any]]:
        try:
            return [item async for item in self.paged("/users", {"$select": USER_SELECT, "$top": "999"})]
        except GraphError as exc:
            if exc.status != 400:
                raise
            basic = "id,displayName,mail,userPrincipalName,accountEnabled,jobTitle,department"
            return [item async for item in self.paged("/users", {"$select": basic, "$top": "999"})]

    async def get_user(self, entra_id: str) -> dict[str, Any]:
        try:
            return await self.request("GET", f"/users/{entra_id}", params={"$select": USER_SELECT})
        except GraphError as exc:
            if exc.status != 400:
                raise
            basic = "id,displayName,mail,userPrincipalName,accountEnabled,jobTitle,department"
            return await self.request("GET", f"/users/{entra_id}", params={"$select": basic})

    async def create_user(
        self,
        display_name: str,
        user_principal_name: str,
        password: str,
        job_title: str = "",
        department: str = "",
        usage_location: str = "",
    ) -> dict[str, Any]:
        mail_nickname = user_principal_name.split("@")[0]
        payload: dict[str, Any] = {
            "accountEnabled": True,
            "displayName": display_name,
            "mailNickname": mail_nickname,
            "userPrincipalName": user_principal_name,
            "passwordProfile": {
                "forceChangePasswordNextSignIn": True,
                "password": password,
            },
        }
        if job_title:
            payload["jobTitle"] = job_title
        if department:
            payload["department"] = department
        if usage_location:
            payload["usageLocation"] = usage_location
        return await self.request("POST", "/users", json=payload)

    async def reset_password(self, entra_id: str, password: str, force_change: bool = True) -> None:
        try:
            await self.request(
                "PATCH",
                f"/users/{entra_id}",
                json={
                    "passwordProfile": {
                        "password": password,
                        "forceChangePasswordNextSignIn": force_change,
                    }
                },
            )
        except GraphError as exc:
            if exc.status in {401, 403}:
                raise GraphError(
                    exc.status,
                    exc.message
                    + " Password reset also needs the app registration's service principal to hold the "
                    "Password Administrator or User Administrator directory role.",
                ) from exc
            raise

    async def assign_license(self, entra_id: str, add_sku_ids: list[str], remove_sku_ids: list[str]) -> dict[str, Any]:
        return await self.request(
            "POST",
            f"/users/{entra_id}/assignLicense",
            json={
                "addLicenses": [{"skuId": sku_id, "disabledPlans": []} for sku_id in add_sku_ids],
                "removeLicenses": remove_sku_ids,
            },
        )

    async def list_subscribed_skus(self) -> list[dict[str, Any]]:
        return [item async for item in self.paged("/subscribedSkus")]

    async def patch_user(self, entra_id: str, body: dict[str, Any]) -> dict[str, Any]:
        await self.request("PATCH", f"/users/{entra_id}", json=body)
        return await self.get_user(entra_id)

    async def list_groups(self) -> list[dict[str, Any]]:
        select = "id,displayName,description,mail,mailNickname,securityEnabled,mailEnabled"
        return [item async for item in self.paged("/groups", {"$select": select, "$top": "999"})]

    async def get_group(self, entra_id: str) -> dict[str, Any]:
        select = "id,displayName,description,mail,mailNickname,securityEnabled,mailEnabled"
        return await self.request("GET", f"/groups/{entra_id}", params={"$select": select})

    async def create_group(self, display_name: str, description: str = "") -> dict[str, Any]:
        payload = {
            "displayName": display_name,
            "description": description,
            "mailEnabled": False,
            "mailNickname": _nickname(display_name),
            "securityEnabled": True,
        }
        return await self.request("POST", "/groups", json=payload)

    async def patch_group(self, entra_id: str, body: dict[str, Any]) -> dict[str, Any]:
        await self.request("PATCH", f"/groups/{entra_id}", json=body)
        return await self.get_group(entra_id)

    async def delete_group(self, entra_id: str) -> None:
        await self.request("DELETE", f"/groups/{entra_id}")

    async def list_members(self, group_entra_id: str) -> list[dict[str, Any]]:
        select = "id,displayName,mail,userPrincipalName,accountEnabled"
        return [
            item
            async for item in self.paged(
                f"/groups/{group_entra_id}/members/microsoft.graph.user",
                {"$select": select, "$top": "999"},
            )
        ]

    async def add_member(self, group_entra_id: str, user_entra_id: str) -> None:
        await self.request(
            "POST",
            f"/groups/{group_entra_id}/members/$ref",
            json={"@odata.id": f"{GRAPH}/directoryObjects/{user_entra_id}"},
        )

    async def remove_member(self, group_entra_id: str, user_entra_id: str) -> None:
        await self.request("DELETE", f"/groups/{group_entra_id}/members/{user_entra_id}/$ref")

    async def list_service_principals(self) -> list[dict[str, Any]]:
        params = {
            "$select": SP_SELECT,
            "$filter": "servicePrincipalType eq 'Application'",
            "$top": "999",
        }
        try:
            return [item async for item in self.paged("/servicePrincipals", params)]
        except GraphError:
            return [
                item
                async for item in self.paged("/servicePrincipals", {"$select": SP_SELECT, "$top": "999"})
                if str(item.get("servicePrincipalType") or "Application") == "Application"
            ]

    async def list_app_registrations(self) -> list[dict[str, Any]]:
        return [item async for item in self.paged("/applications", {"$select": APP_REG_SELECT, "$top": "999"})]

    async def list_app_role_assigned_to(self, service_principal_id: str) -> list[dict[str, Any]]:
        return [
            item
            async for item in self.paged(
                f"/servicePrincipals/{service_principal_id}/appRoleAssignedTo",
                {"$select": ASSIGNMENT_SELECT, "$top": "999"},
            )
        ]

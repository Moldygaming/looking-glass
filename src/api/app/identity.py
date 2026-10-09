"""SSO access rules and the local break-glass identity."""

from __future__ import annotations

BREAK_GLASS_OID = "local-break-glass"


def evaluate_sso(
    *,
    disabled: bool,
    in_admin_group: bool,
    has_admin_app_role: bool,
    in_access_group: bool,
    access_group_configured: bool,
    has_portal_access: bool,
) -> tuple[bool, str]:
    """Decide whether an Entra user may enter Looking Glass.

    Platform admins come from the configured Entra admin group (or the
    PlatformAdmin app role). Everyone else needs a role or group assigned
    in the Looking Glass portal, or membership of an optional access group.
    """
    if disabled:
        return False, "This account has been disabled."
    if in_admin_group or has_admin_app_role:
        return True, "admin"
    if has_portal_access:
        return True, "portal"
    if access_group_configured and in_access_group:
        return True, "access_group"
    if access_group_configured:
        return False, "You are not in the Looking Glass access group."
    return False, (
        "You are not in the platform admin group and have not been granted access in Looking Glass. "
        "Ask an administrator to assign you a role in the portal."
    )


def group_ids_match(configured: str, groups: list[str]) -> bool:
    wanted = (configured or "").strip().lower()
    if not wanted:
        return False
    return wanted in {item.strip().lower() for item in groups if item}


def role_match(configured: str, roles: list[str]) -> bool:
    wanted = (configured or "").strip().lower()
    if not wanted:
        return False
    return wanted in {item.strip().lower() for item in roles if item}

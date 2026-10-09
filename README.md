# Looking Glass

Multi-cloud cost management: Azure, AWS and GCP in one place, with Entra ID SSO and tag-based access.

Admins connect multiple cloud instances (several Azure tenants, AWS payers, GCP orgs). Users only see cost that matches the tag scopes on their access groups — for example Infra sees every subscription, account and project tagged `team=infra`. Custom dashboards and rule-based savings recommendations sit on the same authorisation layer.

## Run locally

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000) and sign in with Microsoft Entra ID, or the local break-glass account (`infraadmin` / `admin123+` unless `BREAK_GLASS_USERNAME` / `BREAK_GLASS_PASSWORD` are set).

Seed data is 90 days of multi-cloud spend across two Azure tenants, an AWS payer and a GCP org.

## Access model

1. Users authenticate with **Microsoft Entra ID**.
2. Members of the Entra group in `ENTRA_ADMIN_GROUP_ID` (or the `PlatformAdmin` app role) become platform admins and can enter the product.
3. Everyone else is admitted only after a platform admin assigns a role or access group in **Admin → Users / Access groups**. Tag scopes on those groups control which cost they see.
4. There is **one** local account, for break-glass only. It is never an Entra user.

## Entra ID SSO

1. Register a web app in Microsoft Entra ID.
2. Redirect URI: `http://localhost:3000/api/auth/callback/microsoft-entra-id` (and the production HTTPS equivalent).
3. Create a client secret.
4. Token configuration → optional claims → **groups**: security groups, emit as **Group ID**.
5. Put that admin group's object ID in `ENTRA_ADMIN_GROUP_ID`.
6. Optional app role: `PlatformAdmin` (value must match `ENTRA_ADMIN_ROLE`).
7. Set:

```bash
AUTH_MICROSOFT_ENTRA_ID_ID=<application (client) id>
AUTH_MICROSOFT_ENTRA_ID_SECRET=<client secret>
AUTH_MICROSOFT_ENTRA_ID_TENANT_ID=<directory (tenant) id>
ENTRA_ADMIN_GROUP_ID=<entra security group object id>
BREAK_GLASS_USERNAME=infraadmin          # default
BREAK_GLASS_PASSWORD=admin123+           # default; change in production
```

If a user has too many group memberships for the token (overage), Looking Glass calls Microsoft Graph `checkMemberGroups` for the configured admin/access group IDs. Grant admin consent for `GroupMember.Read.All` if you rely on that fallback.

## What you will need on Azure (hosting deferred)

The app is containerised (`web`, `api`, `worker`). When you are ready to host it:

| Need | Why |
|------|-----|
| **Azure Database for PostgreSQL Flexible Server** | Required. Users, access groups, tag scopes, dashboards, recommendations, and daily cost facts. |
| **Blob Storage** | Required for production ingest. Landing zone for Azure Cost Management exports, AWS CUR files, and GCP billing extracts. |
| **Container Apps** (3) | Web UI, API, and the ingest/recommendation worker. |
| **Key Vault** | Connector credentials (Azure service principals, AWS keys, GCP service accounts). |
| **Entra ID app registration** | SSO. |
| **Container Registry** | Image store for the three containers. |

Do not put live billing exports in the web container. Cost files belong in Blob; facts belong in Postgres.

## Connectors

Each **connection** is one cloud organisation:

- **Azure** — tenant / billing account / management group. Uses Cost Management Query (`Microsoft.CostManagement/query`) when a service principal is configured.
- **AWS** — payer account. Uses Cost Explorer when access keys are present; CUR 2.0 in Blob is the production path.
- **GCP** — billing account / org. Reads a BigQuery billing export table when a service account JSON is stored.

Until credentials are attached, Looking Glass keeps the seeded demo costs so you can build dashboards and access groups immediately.

## Azure DevOps health

Connect an Azure DevOps organisation (name + personal access token) from **Connections**, then open **DevOps health**.

1. Load projects from the organisation and tick the ones to monitor.
2. Run a health check.
3. The report lists repositories with active pull requests, repositories with stale branches (default: no commit in 30 days), and alerts for pipelines that fail consecutively or at a high recent failure rate.

The PAT needs **Code (Read)**, **Build (Read)** and **Project and team (Read)**. A seeded Contoso snapshot is loaded so the dashboard is visible before a live org is connected.

## Tag-based access

1. Open **Admin portal → Access groups**.
2. Create a group (e.g. Infra).
3. Add a tag scope: `team` = `infra` (optionally limited to one provider or connection).
4. Add members by user email or by Entra group object ID.

Cost queries, line items, dashboards and recommendations are fail-closed: no matching group means no data.

## Layout

```
src/web       Next.js UI (Entra SSO + break-glass login, dashboards, admin, DevOps health)
src/api       FastAPI (authorisation, costs, connectors, Azure DevOps health)
src/api/app/worker.py   Ingest + recommendation + DevOps health loop
```

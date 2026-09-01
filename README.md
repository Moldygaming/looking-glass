# Looking Glass

Multi-cloud cost management: Azure, AWS and GCP in one place, with Entra ID SSO and tag-based access.

Admins connect multiple cloud instances (several Azure tenants, AWS payers, GCP orgs). Users only see cost that matches the tag scopes on their access groups — for example Infra sees every subscription, account and project tagged `team=infra`. Custom dashboards and rule-based savings recommendations sit on the same authorisation layer.

## Run locally

```bash
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000) and pick a demo persona:

| Persona | Sees |
|---------|------|
| Avery Chen (admin) | Everything, plus the admin portal |
| Sam Okonkwo (infra) | Cost tagged `team=infra` |
| Priya Shah (project) | Cost tagged `project=alpha` |

Seed data is 90 days of multi-cloud spend across two Azure tenants, an AWS payer and a GCP org.

## Entra ID SSO

1. Register a web app in Microsoft Entra ID.
2. Redirect URI: `http://localhost:3000/api/auth/callback/microsoft-entra-id` (and the production HTTPS equivalent).
3. Create a client secret.
4. Optional app role: `PlatformAdmin` (value must match `ENTRA_ADMIN_ROLE`).
5. Optional group claims so Entra groups can be mapped in **Admin portal → Access groups**.
6. Set:

```bash
AUTH_MICROSOFT_ENTRA_ID_ID=<application (client) id>
AUTH_MICROSOFT_ENTRA_ID_SECRET=<client secret>
AUTH_MICROSOFT_ENTRA_ID_TENANT_ID=<directory (tenant) id>
AUTH_ALLOW_DEMO=false   # production
```

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

## Tag-based access

1. Open **Admin portal → Access groups**.
2. Create a group (e.g. Infra).
3. Add a tag scope: `team` = `infra` (optionally limited to one provider or connection).
4. Add members by user email or by Entra group object ID.

Cost queries, line items, dashboards and recommendations are fail-closed: no matching group means no data.

## Layout

```
src/web       Next.js UI (Entra / demo login, dashboards, admin)
src/api       FastAPI (authorisation, costs, connectors)
src/api/app/worker.py   Ingest + recommendation loop
```

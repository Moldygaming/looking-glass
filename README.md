# Looking Glass

Multi-cloud FinOps and infrastructure operations in one place. Looking Glass connects Azure, AWS and GCP, ingests resource-level cost, scopes visibility by tags, and sits behind Microsoft Entra ID SSO. Admins also run Azure DevOps health checks and (optionally) manage the Entra directory from the same portal.

This repository is a single-deployment product: one Looking Glass instance, many cloud connections. It is not a multi-tenant SaaS.

---

## Contents

1. [What it does](#what-it-does)
2. [Architecture](#architecture)
3. [Repository layout](#repository-layout)
4. [Prerequisites](#prerequisites)
5. [Quick start](#quick-start)
6. [Sign-in and access](#sign-in-and-access)
7. [Microsoft Entra ID SSO](#microsoft-entra-id-sso)
8. [Environment variables](#environment-variables)
9. [Docker](#docker)
10. [Running without Compose](#running-without-compose)
11. [Product surfaces](#product-surfaces)
12. [Connectors](#connectors)
13. [Tag-based access](#tag-based-access)
14. [Privileges](#privileges)
15. [Background worker](#background-worker)
16. [HTTP API](#http-api)
17. [Seed data](#seed-data)
18. [Tests](#tests)
19. [Production notes](#production-notes)
20. [Security](#security)
21. [Troubleshooting](#troubleshooting)

---

## What it does

| Area | Capability |
|------|------------|
| **Cost** | Daily facts per resource, meter and tag. Explorer with hierarchy (management group / account / resource group / resource), daily/weekly/monthly grain, compare series, and filters from ingested facets. |
| **Dashboards** | Report builder. Widgets filter by cloud, category, resource type, service, search and tags. Category lists come from ingested data. |
| **Savings** | Rule-based recommendations: idle compute, unattached disks, orphan public IPs, untagged spend, rightsizing hints. |
| **Connections** | Multiple Azure tenants, AWS payers, GCP orgs, and Azure DevOps organisations. Secrets stored on the connection, not in the web image. |
| **DevOps health** | Per-project monitoring: active pull requests, stale branches, pipelines that fail consecutively or at a high recent rate. |
| **Access** | Entra SSO. An Entra admin group (or `PlatformAdmin` app role) grants platform admins. Everyone else needs a portal role or access group. One local break-glass account. Cost queries are fail-closed on tag scopes. |
| **Entra ops** | Optional Graph-backed directory: users, groups, apps, licenses, templates, bulk CSV, audit. |

Out of scope for this version: chargeback invoicing, Slack/Teams anomaly bots, budget approval workflows, AI-written narratives, selling Looking Glass as isolated per-customer SaaS.

---

## Architecture

```mermaid
flowchart LR
  Browser --> Web["Web<br/>Next.js 15 :3000"]
  Entra["Microsoft Entra ID"] --> Web
  Web -->|"session + X-Internal-Key"| API["API<br/>FastAPI :8000"]
  API --> PG[(PostgreSQL 16)]
  Worker["Worker<br/>ingest + Entra sync"] --> PG
  Worker --> Azure["Azure Cost Management"]
  Worker --> AWS["AWS Cost Explorer / CUR"]
  Worker --> GCP["BigQuery billing export"]
  Worker --> ADO["Azure DevOps REST"]
  Worker --> Blob["Blob / Azurite"]
  Graph["Microsoft Graph"] --> API
```

Three application containers:

| Container | Image target | Role |
|-----------|--------------|------|
| **web** | `web` | UI, Auth.js (Entra + break-glass), BFF at `/api/lg/*` |
| **api** | `api` | Authorisation, costs, IAM, connectors, DevOps, Entra ops |
| **worker** | `worker` | Same API image, `python -m app.worker`. Cost ingest, recommendations, DevOps scans, Entra directory sync |

Postgres holds users, groups, roles, connections, cost facts, dashboards, recommendations and DevOps snapshots. Blob (Azurite locally) is the landing zone for raw cost exports in production. The web container never stores billing files.

The browser never calls the API with a user token directly. NextAuth holds the session; the BFF forwards `X-Internal-Key`, `X-User-Oid`, `X-User-Email`, `X-User-Name`, `X-User-Roles` and `X-User-Groups`.

---

## Repository layout

```
.
├── Dockerfile                 # Multi-target: api, worker, web
├── docker-compose.yml         # Local stack: postgres, azurite, api, worker, web
├── .env.example
├── README.md
└── src
    ├── api                    # FastAPI app + worker
    │   ├── Dockerfile         # API-only build (context: this folder)
    │   ├── requirements.txt
    │   ├── app/
    │   │   ├── main.py        # Lifespan, routers, health
    │   │   ├── worker.py      # Background loops
    │   │   ├── auth.py        # SSO accept, break-glass, current user
    │   │   ├── identity.py    # Access rules
    │   │   ├── acl.py         # Fail-closed cost ACL
    │   │   ├── seed.py
    │   │   ├── connectors/    # azure, aws, gcp, azure_devops
    │   │   ├── entra/         # Graph client, sync, bulk, provision
    │   │   ├── routers/
    │   │   └── services/      # query, hierarchy, recommend, devops
    │   └── tests/
    └── web                    # Next.js App Router
        ├── Dockerfile         # Web-only build (context: this folder)
        ├── auth.ts            # Auth.js providers
        ├── middleware.ts
        └── app/               # Pages + /api/auth + /api/lg BFF
```

---

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2)
- For Entra SSO: a Microsoft Entra tenant where you can register an app and create a security group
- Optional, for live ingest: Azure Cost Management reader on the chosen scope, AWS Cost Explorer / CUR access, a GCP BigQuery billing export, an Azure DevOps PAT

Ports used locally: **3000** (web), **8000** (api), **5432** (postgres), **10000** (Azurite).

---

## Quick start

```bash
cp .env.example .env          # optional; Compose has working defaults
docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000).

Until Entra is configured, use **Emergency local access**:

| | Default (env unset) |
|---|---|
| Username | `infraadmin` |
| Password | `admin123+` |

Override with `BREAK_GLASS_USERNAME` and `BREAK_GLASS_PASSWORD`. Change the password before the stack is reachable beyond your machine.

Seeded demo cost (two Azure tenants, one AWS payer, one GCP org, ~90 days) and a Contoso Azure DevOps snapshot load on first API start so dashboards and health views work before live credentials exist.

Stop:

```bash
docker compose down
```

Wipe the database volume:

```bash
docker compose down -v
```

---

## Sign-in and access

1. **Authenticate** with Microsoft Entra ID (primary) or the single local break-glass account.
2. **Platform admins** are members of `ENTRA_ADMIN_GROUP_ID`, or holders of the `PlatformAdmin` app role (value must match `ENTRA_ADMIN_ROLE`). They land in the Platform Admins access group.
3. **Everyone else** is admitted only after a platform admin assigns a Looking Glass role or access group in **Admin → Users / Access groups**. You can pre-provision an email so membership is waiting on first sign-in.
4. **Unknown Entra users** are refused. A directory row is created so an admin can grant access later. Nobody is auto-promoted from a request header.
5. **Break-glass** (`infraadmin`) cannot be deleted or disabled in the portal.

Granular permissions (FinOps, connections, DevOps, Entra ops) live on **roles**. Roles are assigned to **access groups** (and optionally directly to a user). Tag **scopes** on a group decide which cost rows that group can see.

---

## Microsoft Entra ID SSO

### App registration

1. Entra ID → App registrations → New registration.
2. Redirect URI (Web): `http://localhost:3000/api/auth/callback/microsoft-entra-id` and the production HTTPS equivalent.
3. Certificates & secrets → new client secret.
4. Token configuration → optional claims → **groups**: security groups, emit as **Group ID**.
5. Optional app role: value `PlatformAdmin` (must match `ENTRA_ADMIN_ROLE`).
6. Create a security group for Looking Glass admins. Copy its object ID into `ENTRA_ADMIN_GROUP_ID`.

Delegated Graph for sign-in is `openid profile email User.Read`. If group overage occurs (too many memberships for the token), Looking Glass calls `POST /me/checkMemberGroups` for the configured admin/access group IDs. That fallback needs admin consent for `GroupMember.Read.All`.

### Environment

```bash
AUTH_MICROSOFT_ENTRA_ID_ID=<application (client) id>
AUTH_MICROSOFT_ENTRA_ID_SECRET=<client secret>
AUTH_MICROSOFT_ENTRA_ID_TENANT_ID=<directory (tenant) id>
ENTRA_ADMIN_GROUP_ID=<admin security group object id>
# optional
ENTRA_ACCESS_GROUP_ID=<group that may sign in before a portal role is assigned>
ENTRA_ADMIN_ROLE=PlatformAdmin
```

### Directory management (optional)

Admin → Entra tenants stores Graph credentials per tenant (application permissions with admin consent: `User.ReadWrite.All`, `Group.ReadWrite.All`, `Directory.Read.All`). You can also bootstrap one tenant with `ENTRA_TENANT_ID` / `ENTRA_CLIENT_ID` / `ENTRA_CLIENT_SECRET`. That is separate from SSO.

---

## Environment variables

Copy `.env.example` to `.env`. Compose reads these for interpolation. Empty values fall back to the defaults shown.

### Core

| Variable | Default | Used by | Purpose |
|----------|---------|---------|---------|
| `APP_ENV` | `development` | api | Runtime label |
| `APP_SECRET` | `change-me` | api | Reserved app secret |
| `INTERNAL_API_KEY` | `dev-internal-key` | api, web | Shared key on every BFF → API call |
| `DATABASE_URL` | compose Postgres URL | api, worker | SQLAlchemy async URL (`postgresql+asyncpg://…`) |
| `WEB_ORIGIN` | `http://localhost:3000` | api | CORS |
| `SEED_ON_STARTUP` | `true` (api), `false` (worker) | api, worker | Load demo cost if the database is empty |
| `API_URL` | `http://api:8000` | web | Server-side BFF and SSO evaluation |
| `AUTH_SECRET` | compose placeholder | web | Auth.js cookie encryption. Set a long random string. |
| `NEXTAUTH_URL` / `AUTH_URL` | `http://localhost:3000` | web | Public origin for callbacks |

### Break-glass

| Variable | Default | Used by |
|----------|---------|---------|
| `BREAK_GLASS_USERNAME` | `infraadmin` | api, web |
| `BREAK_GLASS_PASSWORD` | `admin123+` | api, web |
| `AUTH_BREAK_GLASS_USERNAME` | same | web (preferred name) |
| `AUTH_BREAK_GLASS_PASSWORD` | same | web (preferred name) |

If the variable is unset or empty, the default above is used.

### Entra SSO

| Variable | Used by | Purpose |
|----------|---------|---------|
| `AUTH_MICROSOFT_ENTRA_ID_ID` | web, api (as `ENTRA_CLIENT_ID` if you pass it through) | App (client) ID |
| `AUTH_MICROSOFT_ENTRA_ID_SECRET` | web | Client secret |
| `AUTH_MICROSOFT_ENTRA_ID_TENANT_ID` | web | Tenant ID |
| `ENTRA_ADMIN_GROUP_ID` | api, web | Security group whose members become platform admins |
| `ENTRA_ACCESS_GROUP_ID` | api, web | Optional extra group allowed to sign in |
| `ENTRA_ADMIN_ROLE` | api | App-role value (`PlatformAdmin`) |

### Entra directory bootstrap

| Variable | Default | Used by |
|----------|---------|---------|
| `ENTRA_TENANT_ID` | empty | api, worker |
| `ENTRA_CLIENT_ID` | empty | api, worker |
| `ENTRA_CLIENT_SECRET` | empty | api, worker |
| `ENTRA_SYNC_INTERVAL_SECONDS` | `3600` | api, worker |

### Blob (cost export landing zone)

| Variable | Local default | Used by |
|----------|---------------|---------|
| `BLOB_ENDPOINT` | Azurite URL | api, worker |
| `BLOB_ACCOUNT` | `devstoreaccount1` | api, worker |
| `BLOB_KEY` | Azurite well-known key | api, worker |
| `BLOB_CONTAINER` | `cost-exports` | api, worker |

### Worker

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORKER_INTERVAL_SECONDS` | `21600` (6 hours) | Cost ingest + recommendations + DevOps scans |

---

## Docker

A single root [`Dockerfile`](Dockerfile) builds every application image with `--target`.

```bash
docker build --target api    -t looking-glass-api .
docker build --target worker -t looking-glass-worker .
docker build --target web    -t looking-glass-web .
```

| Target | Base | Runs as | Listens | Health |
|--------|------|---------|---------|--------|
| `api` | `python:3.12-slim` | uid 10001 | 8000 | `GET /health` |
| `worker` | same as api | uid 10001 | none | process |
| `web` | `node:22-alpine` | `app` | 3000 | `GET /api/config` |

`docker compose up --build` builds those targets and starts:

| Service | Image | Ports |
|---------|-------|-------|
| `postgres` | `postgres:16-alpine` | 5432 |
| `azurite` | `mcr.microsoft.com/azure-storage/azurite` | 10000 |
| `api` | `looking-glass-api` | 8000 |
| `worker` | `looking-glass-worker` | — |
| `web` | `looking-glass-web` | 3000 |

Per-folder Dockerfiles remain for isolated builds:

```bash
docker build -t looking-glass-api ./src/api
docker build -t looking-glass-web ./src/web
docker run --rm looking-glass-api python -m app.worker   # worker from the API image
```

Useful Compose commands:

```bash
docker compose logs -f api web worker
docker compose exec api curl -fsS http://127.0.0.1:8000/health
docker compose restart worker
```

---

## Running without Compose

Postgres 16 must be reachable. From `src/api`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://lookingglass:lookingglass@localhost:5432/lookingglass
export INTERNAL_API_KEY=dev-internal-key
uvicorn app.main:app --reload --port 8000
# other terminal
python -m app.worker
```

From `src/web`:

```bash
npm install
export API_URL=http://localhost:8000
export INTERNAL_API_KEY=dev-internal-key
export AUTH_SECRET=dev-auth-secret-change-me-please-32ch
npm run dev
```

---

## Product surfaces

All routes except `/login`, `/api/auth/*` and `/api/config` require a session.

| Path | Privilege | Purpose |
|------|-----------|---------|
| `/` | `finops.costs.read` | Organisation spend overview |
| `/costs` | `finops.costs.read` | Cost explorer: hierarchy, grain, compare, tags |
| `/dashboards` | `finops.dashboards.read` | List / create dashboards |
| `/dashboards/{id}` | `finops.dashboards.write` to edit | Widget report builder |
| `/recommendations` | `finops.recommendations.*` | Savings list and accept/dismiss |
| `/connections` | `connections.read` / `.write` | Cloud and DevOps connectors |
| `/devops` | `devops.read` / `.write` | Project picker and health report |
| `/entra/*` | `admin.entra.read` / helpdesk / write | Directory, licenses, bulk, audit |
| `/admin/*` | `admin.*` or platform admin | Users, groups, roles, privileges, Entra tenants |

### Cost explorer

- Hierarchy keys `kind:value` for management group, subscription/account/project, resource group, resource.
- Resource types are colour-coded.
- Facets (`provider`, `category`, `resource_type`, `service`) are distinct values from ingested lines, not a hardcoded catalogue.
- Filters: provider, category, resource type, service, free-text, tag key/value, multiple AND tag filters, selected item keys for growth-over-time.

### Dashboards

Widgets: KPI, timeseries, breakdown, table, recommendations. Each widget has its own query (cloud, category, type, service, tags, grain, compare keys). Create uses the name **Untitled dashboard** when the field is empty.

### Recommendations (rules, last 14 days)

| Kind | Trigger |
|------|---------|
| `unattached_disk` | Managed Disk / EBS / Persistent Disk without `attached_to` |
| `idle_compute` | VM / EC2 / GCE with near-zero usage |
| `orphan_ip` | Public / Elastic / External IP without `attached_to` |
| `untagged` | Missing `team` and `project` |
| rightsizing hint | Low-but-nonzero idle compute usage |

---

## Connectors

Each **connection** is one cloud organisation. Configure it under **Connections**. Secrets (`client_secret`, AWS keys, service account JSON, PAT) are stored on the connection and never returned to the browser.

### Azure

- Tenant ID, app (client) ID, client secret.
- Scope: subscription, management group or billing account.
- Ingest uses Cost Management Query (`Microsoft.CostManagement/query`). Groupings stay within the API limit of two. Management groups expand to subscriptions. 429s are retried.
- The principal needs Cost Management read on that scope.

### AWS

- Account ID, region, access key, secret, optional CUR URI.
- Live path: Cost Explorer. Production landing zone: CUR 2.0 in Blob.

### GCP

- Project ID, BigQuery billing export table, service account JSON.

### Azure DevOps

- Organisation name or `https://dev.azure.com/{org}`, PAT.
- PAT scopes: **Code (Read)**, **Build (Read)**, **Project and team (Read)**.
- Load projects, tick which to monitor, run a scan.
- Stale branch: non-default, no commit for `stale_days` (default 30).
- Pipeline alert: 3 consecutive failures, or failure rate ≥ 75% of the last 8 runs (configurable).
- Ingest without a PAT is skipped; the seeded Contoso snapshot remains until a live org is connected.

Until live credentials exist, seeded demo costs stay so you can build dashboards and access groups.

---

## Tag-based access

1. **Admin → Access groups** → create a group (for example Infra).
2. Add a scope: tag key `team`, value `infra` (optionally limited to one provider or connection).
3. Assign a role that includes `finops.costs.read` (and whatever else the group needs).
4. Add members by Looking Glass user, email, Entra object ID, or Entra group object ID.

Cost queries, line items, dashboards and recommendations are **fail-closed**: no matching scope means no rows. Platform admins bypass scopes.

Example: Infra sees every Azure subscription, AWS account and GCP project whose resources carry `team=infra`. Project Alpha is scoped to `project=alpha`.

---

## Privileges

Roles are bundles of these keys. `platform.admin` bypasses every check and every data scope.

| Key | Module |
|-----|--------|
| `platform.admin` | Platform |
| `admin.users.read` / `admin.users.write` | Admin |
| `admin.groups.read` / `admin.groups.write` | Admin |
| `admin.roles.read` / `admin.roles.write` | Admin |
| `admin.entra.read` | Infrastructure |
| `admin.entra.helpdesk` | Infrastructure |
| `admin.entra.write` | Infrastructure |
| `connections.read` / `connections.write` | Infrastructure |
| `finops.costs.read` | FinOps |
| `finops.recommendations.read` / `.write` | FinOps |
| `finops.dashboards.read` / `.write` | FinOps |
| `devops.read` / `devops.write` | DevOps |

The last platform administrator cannot be deleted, disabled, or stripped of admin.

---

## Background worker

`python -m app.worker` runs two loops:

| Loop | Interval | Work |
|------|----------|------|
| ingest | `WORKER_INTERVAL_SECONDS` (default 6 hours) | Every connection: cost ingest or DevOps scan; then refresh recommendations |
| entra | `ENTRA_SYNC_INTERVAL_SECONDS` (default 1 hour) | Graph sync for each configured tenant |

Manual ingest: **Connections → Ingest**. Manual DevOps scan: **DevOps health → Run health check**. Manual directory sync: **Admin → Entra**.

---

## HTTP API

The API listens on `:8000`. Browser traffic should go through the web BFF (`/api/lg/...`). Direct calls need:

```
X-Internal-Key: <INTERNAL_API_KEY>
X-User-Oid: <entra oid or local-break-glass>
X-User-Email: <email>
X-User-Name: <display name>
X-User-Roles: <comma-separated token roles>
X-User-Groups: <comma-separated Entra group ids>
```

| Prefix | Purpose |
|--------|---------|
| `GET /health` | Liveness (`{"ok": true, "service": "looking-glass-api"}`) |
| `POST /auth/sso` | Entra sign-in gate (internal key only, no user headers) |
| `GET /me` | Current user, privileges, scopes |
| `/costs/*` | summary, series, breakdown, rollups, tree, compare, line-items, facets, objects, tags |
| `/dashboards` | CRUD |
| `/recommendations` | list, summary, patch status |
| `/connections` | CRUD, test, ingest |
| `/devops/*` | connections, report, projects, scan |
| `/admin/*` | users, groups, roles, privileges, jobs |
| `/entra/*` | tenants, directory, apps |
| `/entra` ops | licenses, templates, bulk, audit, password reset |

`POST /auth/sso` body: `{ "oid", "email", "display_name", "groups", "roles" }`. Allowed reasons: `admin`, `portal`, `access_group`. Denied identities receive 403.

---

## Seed data

On first API start (`SEED_ON_STARTUP=true` and an empty connections table):

- Break-glass user `infraadmin`
- Platform Admins, Infra (`team=infra`), Project Alpha (`project=alpha`)
- Platform administrator role and a Cost access role
- ~90 days of multi-cloud spend
- Organisation overview and Infra estate dashboards (owned by break-glass)
- Contoso Engineering Azure DevOps snapshot (Platform, Website, Payments monitored; Archive not)

Startup always ensures IAM, the break-glass account, and removes leftover demo persona rows (`demo-admin`, `demo-infra`, …) from earlier builds.

---

## Tests

From `src/api` (needs the same Python deps as the API, including SQLAlchemy for connector tests):

```bash
cd src/api
PYTHONPATH=. python3 -m unittest discover -s tests -v
```

| File | Coverage |
|------|----------|
| `tests/test_identity.py` | SSO allow/deny, group and role matching |
| `tests/test_azure_devops.py` | Org URL parse, stale branches, pipeline failure rules |
| `tests/test_entra_bulk.py` | Bulk CSV and license shapes |

There is no separate frontend test suite; verify UI against Compose at [http://localhost:3000](http://localhost:3000).

---

## Production notes

Hosting IaC is not in this repo yet. The app is already containerised for Azure Container Apps (or any orchestrator) in **UK South**.

| Need | Why |
|------|-----|
| Azure Database for PostgreSQL Flexible Server | Users, IAM, dashboards, cost facts |
| Blob Storage | Cost export landing zone |
| Three containers | web, api, worker |
| Key Vault | Connector secrets and `AUTH_SECRET` / `INTERNAL_API_KEY` / break-glass password |
| Entra app registration | SSO |
| Container Registry | Image store |

Set `SEED_ON_STARTUP=false` once you no longer want demo cost. Point `DATABASE_URL` and blob settings at managed services. Set `AUTH_SECRET`, `INTERNAL_API_KEY` and `BREAK_GLASS_PASSWORD` to strong unique values. Serve the web origin over HTTPS and register that redirect URI in Entra.

Do not put live billing exports in the web container.

---

## Security

- Entra is the identity provider. Portal roles are the authorisation source after first admin bootstrap.
- The BFF is the only caller that holds `INTERNAL_API_KEY`. Treat a leak of that key as impersonation of any `X-User-Oid`.
- Cost ACL is fail-closed on tag scopes.
- Connector secrets are stored on the connection record and stripped from API responses.
- Break-glass is a single local account. It is not an Entra user and cannot be deleted in the UI.
- Images run as a non-root user.
- Auth.js cookies are encrypted with `AUTH_SECRET`.

---

## Troubleshooting

| Symptom | What to check |
|---------|----------------|
| Login shows Entra is not configured | `AUTH_MICROSOFT_ENTRA_ID_ID` and `AUTH_MICROSOFT_ENTRA_ID_TENANT_ID` on the **web** service |
| Entra sign-in then “do not have access” | User is outside `ENTRA_ADMIN_GROUP_ID` and has no portal role/group. Confirm group claims on the token. Grant access in Admin → Users. |
| Group claims missing | App registration → Token configuration → groups as Group ID. For overage, consent `GroupMember.Read.All`. |
| Break-glass rejected | Username/password vs `BREAK_GLASS_*`. Defaults are `infraadmin` / `admin123+`. |
| API 401 Missing or invalid internal key | `INTERNAL_API_KEY` must match on web and api |
| API 403 not provisioned | Session oid is unknown. Sign in via Entra or break-glass after a fresh seed. |
| Azure ingest 400 / 429 | Scope and principal; Cost Management allows two groupings; 429s are retried |
| DevOps scan skipped | PAT missing; connection keeps the seeded snapshot |
| Empty cost for a non-admin | No tag scope on their groups — fail-closed |
| Demo users still listed | Restart api after this codebase; leftover `demo-*` rows are purged on startup. Delete any other user from Admin → Users (except break-glass). |
| Docker daemon not running | Start Docker Desktop, then `docker compose up --build` |
| Port already allocated | Stop the previous stack or change the published ports in `docker-compose.yml` |

Logs:

```bash
docker compose logs -f api
docker compose logs -f web
docker compose logs -f worker
```
)

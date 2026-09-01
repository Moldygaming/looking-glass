# Azure Deployment Plan

> **Status:** Executing (application scaffold). Azure hosting/IaC deferred by user.

Generated: 2026-08-29
Updated: 2026-08-29

---

## 1. Project Overview

**Goal:** Build **Looking Glass**, a multi-cloud cost management (FinOps) platform. Users authenticate with Microsoft Entra ID (Azure AD) SSO. Admins connect multiple Azure tenants, AWS accounts, and GCP organisations; ingest granular cost data; control visibility with tag-based access groups; build custom dashboards; and receive savings recommendations.

**Path:** New Project

**Product name:** Looking Glass

---

## 2. Requirements

| Attribute | Value |
|-----------|-------|
| Classification | Production |
| Scale | Medium |
| Budget | Deferred — user asked to ignore hosting for now; app still designed for Azure Container Apps |
| Compliance | UK South, no extra regulatory controls |
| **Subscription** | Deferred by user (do not provision yet) |
| **Location** | `uksouth` |

### Product requirements (from user)

- Multi-cloud cost ingestion: **Azure, AWS, GCP**
- Full organisation access (billing/org-level, not a single subscription)
- Multiple cloud instances per provider (multiple Azure tenants, AWS orgs/accounts, GCP orgs/billing accounts)
- Granular cost data (resource / meter / tag / day)
- Custom dashboards for cost visibility
- Savings recommendations
- Entra ID SSO
- Admin portal: groups that decide who can see which cost data
- Access scoping by **tags** (e.g. Infra group sees all subscriptions/accounts tagged `team=infra`)

### Explicitly out of scope for v1 (start with the above)

- Chargeback/showback invoicing
- Anomaly alerting / Slack-Teams bots
- Budget workflows and approvals
- AI-generated narrative recommendations (rule-based first; SpaceXAI later)
- Multi-tenant SaaS isolation for selling Looking Glass as a product (single deployment, many cloud connections)

---

## 3. Components Detected

Empty workspace (git only). No existing application, Azure config, or Dockerfiles.

| Component | Type | Technology | Path |
|-----------|------|------------|------|
| web | SSR Web App | Next.js 15 + TypeScript | `src/web` |
| api | REST API | FastAPI + Python 3.12 | `src/api` |
| worker | Background / scheduled | Python 3.12 | `src/worker` |

### Dependencies

| Component | Depends On | Type |
|-----------|-----------|------|
| web | api | HTTP |
| web | Entra ID | OIDC |
| api | PostgreSQL | Database |
| api | Key Vault | Secrets (cloud connector credentials) |
| api | Entra ID | JWT validation |
| worker | PostgreSQL | Database |
| worker | Blob Storage | Raw cost exports |
| worker | Key Vault | Connector credentials |
| worker | Cloud APIs | Azure Cost Management, AWS CUR/CE, GCP Billing |

### Existing Infrastructure

| Item | Status |
|------|--------|
| azure.yaml | Not found |
| infra/ | Not found |
| Dockerfiles | Not found |

---

## 4. Recipe Selection

**Selected:** AZD (Bicep)

**Rationale:**
- New multi-service app (web + API + worker)
- Azure-hosted (Entra ID SSO, Azure is the control plane)
- `azd up` is the simplest repeatable deploy path
- Bicep is the default IaC for new azd projects
- Connectors talk *out* to AWS/GCP APIs; the platform itself is not multi-cloud hosted

---

## 5. Architecture

**Stack:** Containers

Host web, API, and worker on Azure Container Apps. Cost ingestion is long-running and file-heavy (CUR, Cost Management exports), which is a poor fit for short-lived Functions as the primary worker. A timer-triggered Container Apps Job (or in-process scheduler in the worker) pulls exports on a schedule.

### Service Mapping

| Component | Azure Service | SKU |
|-----------|---------------|-----|
| web | Container Apps | Consumption, 0.25 vCPU / 0.5 Gi, min replicas 0 (dev) |
| api | Container Apps | Consumption, 0.5 vCPU / 1 Gi, min replicas 0 (dev) |
| worker | Container Apps (or Job) | Consumption, 0.5 vCPU / 1 Gi, min replicas 0 |
| postgres | Azure Database for PostgreSQL Flexible Server | Burstable B1ms, PostgreSQL 16, 32 GiB |
| raw-exports | Storage Account (Blob) | Standard LRS |
| images | Azure Container Registry | Basic |
| secrets | Key Vault | Standard |
| identity | User-assigned Managed Identity | n/a |
| sso | Microsoft Entra ID app registration | Single-tenant (home tenant) |

### Supporting Services

| Service | Purpose |
|---------|---------|
| Log Analytics | Centralized logging |
| Application Insights | Monitoring & APM |
| Key Vault | Secrets (Entra client secret if used, AWS keys, GCP SA JSON, export SAS) |
| Managed Identity | App → Postgres, Key Vault, Storage, ACR (passwordless) |

### Application architecture

```
                    ┌─────────────────────────┐
                    │  Microsoft Entra ID     │
                    │  (SSO + optional groups)│
                    └───────────┬─────────────┘
                                │ OIDC
                    ┌───────────▼─────────────┐
                    │  Looking Glass Web      │
                    │  Next.js (dashboards,   │
                    │  admin portal)          │
                    └───────────┬─────────────┘
                                │ REST + session/JWT
                    ┌───────────▼─────────────┐
     connectors     │  Looking Glass API      │────── PostgreSQL
  Azure / AWS / GCP │  FastAPI                │          │
                    └───────────┬─────────────┘          │
                                │ enqueue / schedule     │
                    ┌───────────▼─────────────┐          │
                    │  Worker                 │──────────┘
                    │  ingest + recommend     │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  Blob: raw cost exports │
                    └─────────────────────────┘
```

### AuthN / AuthZ model

**Authentication**
- Entra ID SSO via OIDC Authorization Code + PKCE
- Web app registration (SPA/web redirect) and API app registration (audience)
- App roles: `PlatformAdmin`, `Analyst` (default authenticated user)
- Only `PlatformAdmin` can open the admin portal

**Authorisation (tag-based data access)**
- Admins create **Access Groups** in the admin portal
- Each group has one or more **tag scopes**, e.g. `team=infra`, `costCenter=platform`, `env=prod`
- Members are Entra users and/or Entra groups
- Cost queries are **always** filtered: a user sees a cost row only if **every required tag on the row's resource/account/subscription matches at least one of their groups' scopes**
- Matching is on cloud resource tags plus inherited account/subscription/project tags
- `PlatformAdmin` bypasses tag filters (full organisation view)
- Users in no groups see no cost data (fail-closed)

**Cloud connections (multiple instances)**
- A **Connection** is one billing/org credential set:
  - Azure: Entra tenant + billing account or management group / subscription list (service principal or federated credential in Key Vault)
  - AWS: payer account + CUR/S3 (IAM role or access keys in Key Vault)
  - GCP: billing account + BigQuery export (service account JSON in Key Vault)
- Many connections per provider are first-class
- Ingestion is per-connection, idempotent by `(connection_id, usage_date, resource_id, meter_id)`

### Data model (v1)

PostgreSQL is the system of record. Cost facts live in a daily-partitioned table. Raw files stay in Blob (and later can feed Azure Data Explorer if volume outgrows Postgres).

| Table | Purpose |
|-------|---------|
| `users` | Cached Entra identity (oid, upn, display name, roles) |
| `access_groups` | Admin-defined groups |
| `access_group_members` | User oid or Entra group id |
| `access_group_scopes` | Tag key/value (and optional connection/provider filter) |
| `connections` | Cloud instance metadata (provider, name, status, scope) |
| `connection_secrets` | Key Vault secret URI only — never the secret itself |
| `resources` | Normalised resource inventory (id, name, type, region, tags jsonb) |
| `cost_line_items` | Granular cost: date, connection, resource, service, meter, tags, cost, currency, usage |
| `dashboards` | User/shared dashboard definitions |
| `dashboard_widgets` | Query + viz config (JSON) |
| `recommendations` | Savings findings (type, resource, estimated monthly save, status) |

### Cost granularity

Normalise all providers into one fact grain:

- `usage_date` (UTC day)
- `provider` + `connection_id`
- `account_id` (subscription / AWS account / GCP project)
- `resource_id`
- `service` / `category` / `meter`
- `region`
- `tags` (jsonb)
- `cost_unblended`, `cost_amortized` (nullable), `currency`
- `usage_quantity` + `usage_unit`

Azure: Cost Management Exports (actual + amortized) to Blob, then parse.  
AWS: Cost and Usage Report (CUR 2.0) in S3, pulled by worker.  
GCP: Cloud Billing export to BigQuery, queried/exported by worker.

v1 ships **Azure connector fully**, AWS and GCP as connection UI + ingestion adapters with the same fact schema (stubs if credentials are absent).

### Dashboards

- Users create dashboards (private or shared to an access group)
- Widgets: time series, breakdown (service / subscription / tag / resource), table, KPI, recommendation list
- Every widget query runs through the same tag-scope authorisation layer
- Filters: date range, connection, provider, tag, service, region

### Recommendations (rule-based v1)

Worker evaluates after each ingest:

| Rule | Signal | Typical save |
|------|--------|----------------|
| Unattached disk | Disk with no owner VM and cost > 0 | Disk monthly cost |
| Idle compute | VM/instance CPU ~0 with running cost | Compute monthly cost |
| Orphan public IP / LB | Resource with no attached NIC | IP/LB cost |
| Untagged spend | Cost missing required org tags | Visibility / allocation |
| Right-size hint | Sustained low utilisation vs SKU | SKU delta (best-effort) |

Each recommendation is scoped by the same tag ACL so users only see findings on resources they can already see.

### Local development

- Docker Compose: Postgres 16 + Azurite (blob) + web + api + worker
- Entra: redirect `http://localhost:3000/api/auth/callback/microsoft-entra-id`
- Seed data: synthetic multi-cloud cost + tags so dashboards and ACL work without live billing exports

---

## 6. Execution Checklist

### Phase 1: Planning
- [x] Analyze workspace — NEW, empty repo
- [x] Gather requirements — Production, medium scale, UK South
- [x] Confirm subscription and location with user — location uksouth; subscription deferred
- [x] Scan codebase — no application files
- [x] Select recipe — AZD (Bicep) when hosting is taken up
- [x] Plan architecture
- [x] **User approved this plan** (stack + product). Hosting/IaC explicitly deferred.

### Phase 2: Execution
- [ ] Research components (load references, invoke skills)
- [ ] Generate infrastructure files
- [ ] Generate application configuration
- [ ] Generate Dockerfiles (if containerized)
- [ ] Scaffold Looking Glass application (auth, admin ACL, connectors, costs, dashboards, recommendations)
- [ ] Update plan status to "Ready for Validation"

### Phase 3: Validation
- [ ] Invoke azure-validate skill
- [ ] All validation checks pass
- [ ] Update plan status to "Validated"
- [ ] Record validation proof below

### Phase 4: Deployment
- [ ] Invoke azure-deploy skill
- [ ] Deployment successful
- [ ] Update plan status to "Deployed"

---

## 7. Validation Proof

> Populated by azure-validate. Empty until validation runs.

| Check | Command Run | Result | Timestamp |
|-------|-------------|--------|-----------|
| | | | |

**Validated by:**  
**Validation timestamp:**

---

## 8. Files to Generate

| File | Purpose | Status |
|------|---------|--------|
| `.azure/plan.md` | This plan | ✅ |
| `azure.yaml` | AZD configuration | ⏸ deferred |
| `infra/main.bicep` | Infrastructure | ⏸ deferred |
| `src/web/Dockerfile` | Web container | ✅ |
| `src/api/Dockerfile` | API + worker container | ✅ |
| `src/web/**` | Next.js app (SSO, dashboards, admin) | ✅ |
| `src/api/**` | FastAPI (authz, costs, admin APIs, worker) | ✅ |
| `docker-compose.yml` | Local Postgres + Azurite + apps | ✅ |
| `.env.example` | Required secrets/config | ✅ |

---

## 9. Next Steps

> Current: Executing application scaffold. Azure resource provisioning skipped until the user asks.

When hosting is resumed, Looking Glass will need:
1. **PostgreSQL Flexible Server** (system of record: users, ACL, cost facts, dashboards)
2. **Blob Storage** (raw Azure Cost Management exports, AWS CUR, GCP billing files)
3. **Container Apps** (web, api, worker)
4. **Key Vault** (cloud connector credentials)
5. **Entra ID app registration** (SSO)
6. Then generate `azure.yaml` + Bicep and run azure-validate before `azd up`

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class GroupRef(BaseModel):
    id: UUID
    name: str


class RoleRef(BaseModel):
    id: UUID
    name: str
    is_system: bool = False


class CurrentUser(BaseModel):
    id: UUID
    entra_oid: str
    email: str
    display_name: str
    roles: list[str]
    entra_group_ids: list[str]
    status: str = "active"
    is_admin: bool
    group_ids: list[UUID] = Field(default_factory=list)
    groups: list[GroupRef] = Field(default_factory=list)
    privileges: list[str] = Field(default_factory=list)
    direct_privileges: list[str] = Field(default_factory=list)
    access_roles: list[RoleRef] = Field(default_factory=list)
    scopes: list["ScopeOut"] = Field(default_factory=list)

    def has(self, *keys: str) -> bool:
        if self.is_admin or "platform.admin" in self.privileges:
            return True
        granted = set(self.privileges)
        return any(key in granted for key in keys)


class ScopeIn(BaseModel):
    tag_key: str
    tag_value: str
    provider: str | None = None
    connection_id: UUID | None = None


class ScopeOut(ScopeIn):
    id: UUID


class MemberIn(BaseModel):
    user_id: UUID | None = None
    entra_oid: str | None = None
    entra_group_id: str | None = None
    email: str | None = None


class MemberOut(MemberIn):
    id: UUID
    display_name: str | None = None
    kind: str = "user"


class GroupIn(BaseModel):
    name: str
    description: str = ""
    role_ids: list[UUID] = Field(default_factory=list)


class GroupOut(BaseModel):
    id: UUID
    name: str
    description: str
    is_system: bool = False
    created_at: datetime
    members: list[MemberOut] = Field(default_factory=list)
    scopes: list[ScopeOut] = Field(default_factory=list)
    roles: list[RoleRef] = Field(default_factory=list)
    privileges: list[str] = Field(default_factory=list)


class ConnectionSecretsIn(BaseModel):
    client_secret: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None
    service_account_json: str | None = None


class ConnectionIn(BaseModel):
    name: str
    provider: Literal["azure", "aws", "gcp"]
    config: dict[str, Any] = Field(default_factory=dict)
    secrets: ConnectionSecretsIn | None = None
    secret_ref: str | None = None


class ConnectionUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    secrets: ConnectionSecretsIn | None = None
    secret_ref: str | None = None


class ConnectionOut(BaseModel):
    id: UUID
    name: str
    provider: str
    status: str
    config: dict[str, Any]
    credentials_configured: bool
    last_ingest_at: datetime | None
    last_error: str | None
    created_at: datetime


class CostQuery(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    provider: str | None = None
    connection_id: UUID | None = None
    account_id: str | None = None
    service: str | None = None
    region: str | None = None
    group_by: str = "service"
    tag_key: str | None = None
    tag_value: str | None = None
    q: str | None = None
    keys: list[str] | None = None
    focus: list[str] = Field(default_factory=list)
    path: list[str] = Field(default_factory=list)
    granularity: str = "day"
    limit: int = 100
    offset: int = 0


class CostPoint(BaseModel):
    date: date
    cost: float
    amortized_cost: float


class BreakdownRow(BaseModel):
    key: str
    label: str
    cost: float
    amortized_cost: float
    share: float


class LineItemOut(BaseModel):
    id: UUID
    usage_date: date
    provider: str
    connection_id: UUID
    account_id: str
    account_name: str
    resource_id: str
    resource_name: str
    resource_type: str
    service: str
    category: str
    meter: str
    region: str
    tags: dict[str, str]
    cost: float
    amortized_cost: float
    currency: str
    usage_quantity: float
    usage_unit: str


class CostSummary(BaseModel):
    currency: str
    period_cost: float
    prior_period_cost: float
    delta_pct: float
    forecast_month: float
    open_recommendations: int
    potential_monthly_savings: float
    untagged_cost: float
    connections: int
    series: list[CostPoint]
    by_provider: list[BreakdownRow]


class RollupRow(BaseModel):
    key: str
    label: str
    provider: str
    account_id: str = ""
    account_name: str
    resource_group: str = ""
    org_id: str = ""
    org_name: str = ""
    service: str
    period_start: date
    cost: float
    prior_cost: float
    delta_pct: float | None
    currency: str


class HierarchyNode(BaseModel):
    key: str
    kind: str
    label: str
    provider: str
    path: str = ""
    cost: float
    prior_cost: float
    delta_pct: float | None
    currency: str
    service: str = ""
    category: str = ""
    children: list["HierarchyNode"] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class CostObjectOut(BaseModel):
    key: str
    kind: str
    label: str
    provider: str = ""
    path: str = ""
    cost: float
    prior_cost: float
    delta_pct: float | None
    share: float = 0
    currency: str
    service: str = ""
    category: str = ""
    has_children: bool = False


class CostObjectFocus(BaseModel):
    key: str
    kind: str
    label: str


class CostObjectPage(BaseModel):
    path: list[str]
    current_kind: str | None = None
    next_kind: str | None = None
    focus: list[CostObjectFocus] = Field(default_factory=list)
    objects: list[CostObjectOut] = Field(default_factory=list)
    currency: str = "GBP"
    period_cost: float = 0
    prior_period_cost: float = 0
    delta_pct: float | None = None
    object_count: int = 0


class DimensionOut(BaseModel):
    key: str
    label: str
    group: str
    description: str


class HierarchyPresetOut(BaseModel):
    id: str
    name: str
    description: str
    path: list[str]


class DimensionCatalogOut(BaseModel):
    dimensions: list[DimensionOut]
    presets: list[HierarchyPresetOut]
    default_path: list[str]


class SeriesPoint(BaseModel):
    date: date
    cost: float
    amortized_cost: float = 0


class NamedSeries(BaseModel):
    key: str
    label: str
    kind: str = "resource"
    category: str = ""
    cost: float
    prior_cost: float
    delta_pct: float | None
    points: list[SeriesPoint]


class WidgetIn(BaseModel):
    id: str
    type: Literal["kpi", "timeseries", "breakdown", "table", "recommendations", "growth"]
    title: str
    group_by: str = "service"
    date_range: str = "30d"
    granularity: str = "day"
    item_keys: list[str] = Field(default_factory=list)
    provider: str | None = None
    tag_key: str | None = None
    tag_value: str | None = None


class DashboardIn(BaseModel):
    name: str
    description: str = ""
    visibility: Literal["private", "group", "org"] = "private"
    shared_group_id: UUID | None = None
    widgets: list[WidgetIn] = Field(default_factory=list)


class DashboardOut(DashboardIn):
    id: UUID
    owner_user_id: UUID
    created_at: datetime
    updated_at: datetime


class RecommendationOut(BaseModel):
    id: UUID
    connection_id: UUID
    provider: str
    account_id: str
    resource_id: str
    resource_name: str
    category: str
    title: str
    description: str
    monthly_savings: float
    currency: str
    status: str
    tags: dict[str, str]
    evidence: dict[str, Any]
    created_at: datetime


class RecommendationPatch(BaseModel):
    status: Literal["open", "accepted", "dismissed"]


class UserOut(BaseModel):
    id: UUID
    entra_oid: str
    email: str
    display_name: str
    roles: list[str]
    status: str = "active"
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class UserRef(BaseModel):
    id: UUID
    display_name: str
    email: str


class UserCreate(BaseModel):
    email: str
    display_name: str
    entra_oid: str | None = None
    notes: str = ""
    group_ids: list[UUID] = Field(default_factory=list)
    role_ids: list[UUID] = Field(default_factory=list)


class UserPatch(BaseModel):
    display_name: str | None = None
    status: Literal["active", "disabled"] | None = None
    notes: str | None = None


class PrivilegeSet(BaseModel):
    privileges: list[str]


class RoleIdSet(BaseModel):
    role_ids: list[UUID]


class RoleIn(BaseModel):
    name: str
    description: str = ""
    privileges: list[str] = Field(default_factory=list)


class RoleOut(BaseModel):
    id: UUID
    name: str
    description: str
    is_system: bool = False
    created_at: datetime
    privileges: list[str] = Field(default_factory=list)
    groups: list[GroupRef] = Field(default_factory=list)
    users: list[UserRef] = Field(default_factory=list)


class PrivilegeGrantSource(BaseModel):
    kind: Literal["role", "implied"]
    role_id: UUID | None = None
    role_name: str | None = None
    group_id: UUID | None = None
    group_name: str | None = None
    via: str | None = None


class PrivilegeSourceOut(BaseModel):
    key: str
    name: str
    module: str
    sources: list[PrivilegeGrantSource] = Field(default_factory=list)


class UserListOut(BaseModel):
    id: UUID
    entra_oid: str
    email: str
    display_name: str
    roles: list[str]
    status: str
    notes: str = ""
    last_login_at: datetime | None
    created_at: datetime
    is_admin: bool
    groups: list[GroupRef] = Field(default_factory=list)
    access_roles: list[RoleRef] = Field(default_factory=list)
    direct_roles: list[RoleRef] = Field(default_factory=list)
    direct_privileges: list[str] = Field(default_factory=list)
    privilege_count: int = 0


class UserDetailOut(UserListOut):
    entra_group_ids: list[str] = Field(default_factory=list)
    effective_privileges: list[str] = Field(default_factory=list)
    privilege_sources: list[PrivilegeSourceOut] = Field(default_factory=list)
    scopes: list[ScopeOut] = Field(default_factory=list)


class PrivilegeDefOut(BaseModel):
    key: str
    module: str
    name: str
    description: str


class PrivilegeCatalogOut(BaseModel):
    catalog: list[PrivilegeDefOut]


class PrivilegeAssignmentOut(PrivilegeDefOut):
    roles: list[RoleRef] = Field(default_factory=list)
    groups: list[GroupRef] = Field(default_factory=list)
    direct_users: list[UserRef] = Field(default_factory=list)
    effective_user_count: int = 0


class RecentLoginOut(BaseModel):
    id: UUID
    display_name: str
    email: str
    last_login_at: datetime | None
    status: str


class AdminOverview(BaseModel):
    user_count: int
    active_user_count: int
    disabled_user_count: int
    group_count: int
    role_count: int = 0
    users_without_groups: list[UserRef] = Field(default_factory=list)
    groups_without_roles: list[GroupRef] = Field(default_factory=list)
    recent_logins: list[RecentLoginOut] = Field(default_factory=list)


class DirectorySyncOut(BaseModel):
    id: UUID
    started_at: datetime
    finished_at: datetime | None
    status: str
    users_upserted: int
    groups_upserted: int
    memberships_upserted: int
    apps_upserted: int = 0
    assignments_upserted: int = 0
    tenant_id: UUID | None = None
    error: str | None = None


class EntraTenantOut(BaseModel):
    id: UUID
    name: str
    tenant_id: str
    client_id: str
    domain: str = ""
    status: str
    enabled: bool = True
    credentials_configured: bool
    last_error: str | None = None
    last_synced_at: datetime | None = None
    last_sync: DirectorySyncOut | None = None
    created_at: datetime


class EntraTenantCreate(BaseModel):
    name: str
    tenant_id: str
    client_id: str
    client_secret: str
    domain: str = ""


class EntraTenantPatch(BaseModel):
    name: str | None = None
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    domain: str | None = None
    enabled: bool | None = None


class EntraStatusOut(BaseModel):
    configured: bool
    tenant_count: int = 0
    last_sync: DirectorySyncOut | None = None
    required_permissions: list[str] = Field(default_factory=list)
    tenants: list[EntraTenantOut] = Field(default_factory=list)


class EntraAppRoleOut(BaseModel):
    id: str
    display_name: str
    value: str = ""
    description: str = ""
    enabled: bool = True
    allowed_member_types: list[str] = Field(default_factory=list)


class EntraAppAssignmentRef(BaseModel):
    application_id: UUID
    display_name: str
    app_id: str
    app_role_id: str
    app_role_name: str
    assignment_required: bool = False
    is_microsoft: bool = False
    has_app_registration: bool = False


class AssignedLicenseOut(BaseModel):
    sku_id: str
    sku_part_number: str = ""
    display_name: str = ""
    disabled_plans: list[str] = Field(default_factory=list)


class EntraUserOut(BaseModel):
    id: UUID
    entra_oid: str
    email: str
    display_name: str
    user_principal_name: str = ""
    job_title: str = ""
    department: str = ""
    usage_location: str = ""
    status: str
    source: str = "local"
    entra_tenant_id: UUID | None = None
    last_synced_at: datetime | None = None
    last_login_at: datetime | None = None
    temporary_password: str | None = None
    assigned_licenses: list[AssignedLicenseOut] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    app_assignments: list[EntraAppAssignmentRef] = Field(default_factory=list)


class EntraUserCreate(BaseModel):
    tenant_id: UUID
    display_name: str
    user_principal_name: str
    password: str | None = None
    job_title: str = ""
    department: str = ""
    usage_location: str = ""
    template_id: UUID | None = None


class EntraUserPatch(BaseModel):
    display_name: str | None = None
    job_title: str | None = None
    department: str | None = None
    usage_location: str | None = None
    status: Literal["active", "disabled"] | None = None


class PasswordResetIn(BaseModel):
    password: str | None = None
    force_change: bool = True


class LicenseChangeIn(BaseModel):
    add_sku_ids: list[str] = Field(default_factory=list)
    remove_sku_ids: list[str] = Field(default_factory=list)
    usage_location: str | None = None


class EntraLicenseOut(BaseModel):
    id: UUID
    tenant_id: UUID
    sku_id: str
    sku_part_number: str = ""
    display_name: str = ""
    consumed_units: int = 0
    enabled_units: int = 0
    suspended_units: int = 0
    warning_units: int = 0
    available_units: int = 0
    capability_status: str = ""
    service_plans: list[str] = Field(default_factory=list)


class EntraTemplateOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str = ""
    department: str = ""
    job_title: str = ""
    usage_location: str = ""
    group_ids: list[str] = Field(default_factory=list)
    license_sku_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EntraTemplateIn(BaseModel):
    tenant_id: UUID
    name: str
    description: str = ""
    department: str = ""
    job_title: str = ""
    usage_location: str = ""
    group_ids: list[str] = Field(default_factory=list)
    license_sku_ids: list[str] = Field(default_factory=list)


class EntraTemplatePatch(BaseModel):
    name: str | None = None
    description: str | None = None
    department: str | None = None
    job_title: str | None = None
    usage_location: str | None = None
    group_ids: list[str] | None = None
    license_sku_ids: list[str] | None = None


class EntraBulkIn(BaseModel):
    tenant_id: UUID
    csv: str


class EntraBulkRowOut(BaseModel):
    row: int
    action: str
    user_principal_name: str
    status: str
    detail: str


class EntraBulkOut(BaseModel):
    ok: int
    failed: int
    results: list[EntraBulkRowOut]


class EntraAuditOut(BaseModel):
    id: UUID
    tenant_id: UUID | None = None
    actor_email: str = ""
    actor_name: str = ""
    action: str
    target_type: str = ""
    target_id: str = ""
    target_label: str = ""
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    graph_request_id: str | None = None
    status: str
    error: str | None = None
    created_at: datetime


class EntraMemberOut(BaseModel):
    entra_user_id: str
    user_id: UUID | None = None
    display_name: str | None = None
    email: str | None = None
    user_principal_name: str | None = None
    status: str | None = None


class EntraGroupOut(BaseModel):
    id: UUID
    tenant_id: UUID | None = None
    entra_id: str
    display_name: str
    description: str = ""
    mail: str = ""
    mail_nickname: str = ""
    security_enabled: bool = True
    mail_enabled: bool = False
    member_count: int = 0
    last_synced_at: datetime | None = None
    members: list[EntraMemberOut] = Field(default_factory=list)
    app_assignments: list[EntraAppAssignmentRef] = Field(default_factory=list)


class EntraAppAssignmentOut(BaseModel):
    id: UUID
    assignment_id: str
    principal_id: str
    principal_type: str
    principal_display_name: str
    app_role_id: str
    app_role_name: str
    user_id: UUID | None = None
    group_id: UUID | None = None
    email: str | None = None
    user_principal_name: str | None = None
    status: str | None = None


class EntraAppOut(BaseModel):
    id: UUID
    tenant_id: UUID | None = None
    service_principal_id: str
    app_id: str
    application_object_id: str = ""
    display_name: str
    description: str = ""
    publisher_name: str = ""
    account_enabled: bool = True
    assignment_required: bool = False
    sign_in_audience: str = ""
    homepage: str = ""
    is_microsoft: bool = False
    hidden: bool = False
    has_app_registration: bool = False
    user_assignment_count: int = 0
    group_assignment_count: int = 0
    last_synced_at: datetime | None = None
    app_roles: list[EntraAppRoleOut] = Field(default_factory=list)
    assignments: list[EntraAppAssignmentOut] = Field(default_factory=list)


class EntraGroupCreate(BaseModel):
    tenant_id: UUID
    display_name: str
    description: str = ""


class EntraGroupPatch(BaseModel):
    display_name: str | None = None
    description: str | None = None


class EntraMemberIn(BaseModel):
    entra_user_id: str | None = None
    user_id: UUID | None = None


CurrentUser.model_rebuild()
HierarchyNode.model_rebuild()
EntraStatusOut.model_rebuild()

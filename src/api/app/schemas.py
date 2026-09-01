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


CurrentUser.model_rebuild()
HierarchyNode.model_rebuild()

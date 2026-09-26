export type Scope = {
  id?: string;
  tag_key: string;
  tag_value: string;
  provider?: string | null;
  connection_id?: string | null;
};

export type GroupRef = { id: string; name: string };
export type RoleRef = { id: string; name: string; is_system?: boolean };

export type Me = {
  id: string;
  entra_oid: string;
  email: string;
  display_name: string;
  roles: string[];
  status: string;
  is_admin: boolean;
  groups: GroupRef[];
  privileges: string[];
  direct_privileges: string[];
  access_roles?: RoleRef[];
  scopes: Scope[];
};

export type CostPoint = { date: string; cost: number; amortized_cost: number };
export type BreakdownRow = { key: string; label: string; cost: number; amortized_cost: number; share: number };
export type Granularity = "day" | "week" | "month";

export type RollupRow = {
  key: string;
  label: string;
  provider: string;
  account_name: string;
  service: string;
  period_start: string;
  cost: number;
  prior_cost: number;
  delta_pct: number | null;
  currency: string;
};

export type NamedSeries = {
  key: string;
  label: string;
  kind?: string;
  category?: string;
  cost: number;
  prior_cost: number;
  delta_pct: number | null;
  points: CostPoint[];
};

export type HierarchyNode = {
  key: string;
  kind: string;
  label: string;
  provider: string;
  path: string;
  cost: number;
  prior_cost: number;
  delta_pct: number | null;
  currency: string;
  service?: string;
  category?: string;
  children: HierarchyNode[];
};

export type CostObject = {
  key: string;
  kind: string;
  label: string;
  provider: string;
  path: string;
  cost: number;
  prior_cost: number;
  delta_pct: number | null;
  share: number;
  currency: string;
  service?: string;
  category?: string;
  has_children: boolean;
};

export type CostObjectFocus = { key: string; kind: string; label: string };

export type CostObjectPage = {
  path: string[];
  current_kind: string | null;
  next_kind: string | null;
  focus: CostObjectFocus[];
  objects: CostObject[];
  currency: string;
  period_cost: number;
  prior_period_cost: number;
  delta_pct: number | null;
  object_count: number;
};

export type CostDimension = {
  key: string;
  label: string;
  group: string;
  description: string;
};

export type HierarchyPreset = {
  id: string;
  name: string;
  description: string;
  path: string[];
};

export type DimensionCatalog = {
  dimensions: CostDimension[];
  presets: HierarchyPreset[];
  default_path: string[];
};

export type CostSummary = {
  currency: string;
  period_cost: number;
  prior_period_cost: number;
  delta_pct: number;
  forecast_month: number;
  open_recommendations: number;
  potential_monthly_savings: number;
  untagged_cost: number;
  connections: number;
  series: CostPoint[];
  by_provider: BreakdownRow[];
};

export type LineItems = {
  total: number;
  items: {
    id: string;
    usage_date: string;
    provider: string;
    account_name: string;
    resource_name: string;
    service: string;
    meter: string;
    region: string;
    tags: Record<string, string>;
    cost: number;
    currency: string;
  }[];
};

export type Widget = {
  id: string;
  type: "kpi" | "timeseries" | "breakdown" | "table" | "recommendations" | "growth";
  title: string;
  group_by: string;
  date_range: string;
  granularity?: Granularity;
  item_keys?: string[];
  provider?: string | null;
  tag_key?: string | null;
  tag_value?: string | null;
};

export type Dashboard = {
  id: string;
  name: string;
  description: string;
  visibility: "private" | "group" | "org";
  shared_group_id?: string | null;
  widgets: Widget[];
  owner_user_id: string;
};

export type Recommendation = {
  id: string;
  provider: string;
  account_id: string;
  resource_name: string;
  category: string;
  title: string;
  description: string;
  monthly_savings: number;
  currency: string;
  status: string;
  tags: Record<string, string>;
};

export type Connection = {
  id: string;
  name: string;
  provider: "azure" | "aws" | "gcp" | string;
  status: string;
  config: Record<string, unknown>;
  credentials_configured: boolean;
  last_ingest_at?: string | null;
  last_error?: string | null;
  created_at?: string;
};

export type GroupMember = {
  id: string;
  user_id?: string | null;
  email?: string | null;
  display_name?: string | null;
  entra_oid?: string | null;
  entra_group_id?: string | null;
  kind?: "user" | "entra_group" | string;
};

export type Group = {
  id: string;
  name: string;
  description: string;
  is_system?: boolean;
  created_at?: string;
  members: GroupMember[];
  scopes: Scope[];
  roles: RoleRef[];
  privileges: string[];
};

export type UserRow = {
  id: string;
  entra_oid: string;
  email: string;
  display_name: string;
  roles: string[];
  status: string;
  notes?: string;
  last_login_at?: string | null;
  created_at: string;
  is_admin: boolean;
  groups: GroupRef[];
  access_roles: RoleRef[];
  direct_roles: RoleRef[];
  direct_privileges: string[];
  privilege_count: number;
};

export type PrivilegeGrantSource = {
  kind: "role" | "implied";
  role_id?: string | null;
  role_name?: string | null;
  group_id?: string | null;
  group_name?: string | null;
  via?: string | null;
};

export type PrivilegeSource = {
  key: string;
  name: string;
  module: string;
  sources: PrivilegeGrantSource[];
};

export type UserDetail = UserRow & {
  entra_group_ids: string[];
  effective_privileges: string[];
  privilege_sources: PrivilegeSource[];
  scopes: Scope[];
};

export type PrivilegeDef = {
  key: string;
  module: string;
  name: string;
  description: string;
};

export type PrivilegeCatalog = {
  catalog: PrivilegeDef[];
};

export type AccessRole = {
  id: string;
  name: string;
  description: string;
  is_system?: boolean;
  created_at?: string;
  privileges: string[];
  groups: GroupRef[];
  users: { id: string; display_name: string; email: string }[];
};

export type PrivilegeAssignment = PrivilegeDef & {
  roles: RoleRef[];
  groups: GroupRef[];
  direct_users: { id: string; display_name: string; email: string }[];
  effective_user_count: number;
};

export type AdminOverview = {
  user_count: number;
  active_user_count: number;
  disabled_user_count: number;
  group_count: number;
  role_count?: number;
  users_without_groups: { id: string; display_name: string; email: string }[];
  groups_without_roles: GroupRef[];
  recent_logins: {
    id: string;
    display_name: string;
    email: string;
    last_login_at?: string | null;
    status: string;
  }[];
};

export type DirectorySync = {
  id: string;
  started_at: string;
  finished_at?: string | null;
  status: string;
  users_upserted: number;
  groups_upserted: number;
  memberships_upserted: number;
  apps_upserted?: number;
  assignments_upserted?: number;
  error?: string | null;
};

export type EntraTenant = {
  id: string;
  name: string;
  tenant_id: string;
  client_id: string;
  domain: string;
  status: string;
  enabled: boolean;
  credentials_configured: boolean;
  last_error?: string | null;
  last_synced_at?: string | null;
  last_sync?: DirectorySync | null;
  created_at: string;
};

export type EntraStatus = {
  configured: boolean;
  tenant_count?: number;
  last_sync?: DirectorySync | null;
  required_permissions: string[];
  tenants?: EntraTenant[];
};

export type EntraAppAssignmentRef = {
  application_id: string;
  display_name: string;
  app_id: string;
  app_role_id: string;
  app_role_name: string;
  assignment_required: boolean;
  is_microsoft: boolean;
  has_app_registration: boolean;
};

export type AssignedLicense = {
  sku_id: string;
  sku_part_number: string;
  display_name: string;
  disabled_plans: string[];
};

export type EntraUser = {
  id: string;
  entra_oid: string;
  email: string;
  display_name: string;
  user_principal_name: string;
  job_title: string;
  department: string;
  usage_location?: string;
  status: string;
  source: string;
  entra_tenant_id?: string | null;
  last_synced_at?: string | null;
  last_login_at?: string | null;
  temporary_password?: string | null;
  assigned_licenses?: AssignedLicense[];
  warnings?: string[];
  app_assignments?: EntraAppAssignmentRef[];
};

export type EntraLicense = {
  id: string;
  tenant_id: string;
  sku_id: string;
  sku_part_number: string;
  display_name: string;
  consumed_units: number;
  enabled_units: number;
  suspended_units: number;
  warning_units: number;
  available_units: number;
  capability_status: string;
  service_plans: string[];
};

export type EntraTemplate = {
  id: string;
  tenant_id: string;
  name: string;
  description: string;
  department: string;
  job_title: string;
  usage_location: string;
  group_ids: string[];
  license_sku_ids: string[];
  created_at: string;
  updated_at: string;
};

export type EntraBulkResult = {
  ok: number;
  failed: number;
  results: { row: number; action: string; user_principal_name: string; status: string; detail: string }[];
};

export type EntraAuditEvent = {
  id: string;
  tenant_id?: string | null;
  actor_email: string;
  actor_name: string;
  action: string;
  target_type: string;
  target_id: string;
  target_label: string;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
  graph_request_id?: string | null;
  status: string;
  error?: string | null;
  created_at: string;
};

export type EntraMember = {
  entra_user_id: string;
  user_id?: string | null;
  display_name?: string | null;
  email?: string | null;
  user_principal_name?: string | null;
  status?: string | null;
};

export type EntraGroup = {
  id: string;
  entra_id: string;
  display_name: string;
  description: string;
  mail: string;
  mail_nickname: string;
  security_enabled: boolean;
  mail_enabled: boolean;
  member_count: number;
  last_synced_at?: string | null;
  members: EntraMember[];
  app_assignments?: EntraAppAssignmentRef[];
};

export type EntraAppRole = {
  id: string;
  display_name: string;
  value: string;
  description: string;
  enabled: boolean;
  allowed_member_types: string[];
};

export type EntraAppAssignment = {
  id: string;
  assignment_id: string;
  principal_id: string;
  principal_type: string;
  principal_display_name: string;
  app_role_id: string;
  app_role_name: string;
  user_id?: string | null;
  group_id?: string | null;
  email?: string | null;
  user_principal_name?: string | null;
  status?: string | null;
};

export type EntraApp = {
  id: string;
  service_principal_id: string;
  app_id: string;
  application_object_id: string;
  display_name: string;
  description: string;
  publisher_name: string;
  account_enabled: boolean;
  assignment_required: boolean;
  sign_in_audience: string;
  homepage: string;
  is_microsoft: boolean;
  hidden: boolean;
  has_app_registration: boolean;
  user_assignment_count: number;
  group_assignment_count: number;
  last_synced_at?: string | null;
  app_roles: EntraAppRole[];
  assignments: EntraAppAssignment[];
};

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

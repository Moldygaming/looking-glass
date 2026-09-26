export type Swatch = {
  hex: string;
  chip: string;
  label: string;
};

const KIND: Record<string, Swatch> = {
  provider: { hex: "#818cf8", chip: "bg-indigo-400/15 text-indigo-200 border-indigo-400/30", label: "Cloud" },
  connection: { hex: "#a5b4fc", chip: "bg-indigo-400/15 text-indigo-200 border-indigo-400/30", label: "Connection" },
  org: { hex: "#c084fc", chip: "bg-purple-400/15 text-purple-200 border-purple-400/30", label: "Organisation" },
  management_group: { hex: "#c084fc", chip: "bg-purple-400/15 text-purple-200 border-purple-400/30", label: "Organisation" },
  account: { hex: "#fb923c", chip: "bg-orange-400/15 text-orange-200 border-orange-400/30", label: "Account" },
  subscription: { hex: "#7dd3fc", chip: "bg-sky-400/15 text-sky-200 border-sky-400/30", label: "Account" },
  project: { hex: "#facc15", chip: "bg-yellow-400/15 text-yellow-100 border-yellow-400/30", label: "Account" },
  resource_group: { hex: "#2ee6c7", chip: "bg-teal-400/15 text-teal-200 border-teal-400/30", label: "Resource group" },
  region: { hex: "#38bdf8", chip: "bg-sky-400/15 text-sky-200 border-sky-400/30", label: "Region" },
  category: { hex: "#e879f9", chip: "bg-pink-400/15 text-pink-200 border-pink-400/30", label: "Category" },
  service: { hex: "#34d399", chip: "bg-emerald-400/15 text-emerald-200 border-emerald-400/30", label: "Service" },
  resource_type: { hex: "#fbbf24", chip: "bg-amber-400/15 text-amber-200 border-amber-400/30", label: "Resource type" },
  meter: { hex: "#f472b6", chip: "bg-pink-400/15 text-pink-200 border-pink-400/30", label: "Meter" },
  resource: { hex: "#94a3b8", chip: "bg-slate-400/15 text-slate-200 border-slate-400/30", label: "Resource" },
};

const CATEGORY: Record<string, Swatch> = {
  Compute: { hex: "#7aa2ff", chip: "bg-blue-400/15 text-blue-200 border-blue-400/30", label: "Compute" },
  Storage: { hex: "#f4b942", chip: "bg-amber-400/15 text-amber-200 border-amber-400/30", label: "Storage" },
  Database: { hex: "#d8b4fe", chip: "bg-fuchsia-400/15 text-fuchsia-200 border-fuchsia-400/30", label: "Database" },
  Network: { hex: "#34d399", chip: "bg-emerald-400/15 text-emerald-200 border-emerald-400/30", label: "Network" },
  Security: { hex: "#fb7185", chip: "bg-rose-400/15 text-rose-200 border-rose-400/30", label: "Security" },
  Analytics: { hex: "#e879f9", chip: "bg-pink-400/15 text-pink-200 border-pink-400/30", label: "Analytics" },
  Other: { hex: "#8b9bb4", chip: "bg-slate-400/10 text-mist-400 border-white/10", label: "Other" },
};

export const KIND_LEGEND = Object.entries(KIND).filter(
  ([key]) => !["subscription", "project", "management_group", "resource"].includes(key)
);
export const CATEGORY_LEGEND = Object.values(CATEGORY);

export function classifyCategory(service = "", resourceType = "") {
  const text = `${service} ${resourceType}`.toLowerCase();
  if (/(virtual machine|compute|aks|kubernetes|eks|gke|ec2|ecs|lambda|app service|functions|cloud run|container)/.test(text)) {
    return "Compute";
  }
  if (/(storage|blob|disk|ebs|s3|filestore|backup|glacier)/.test(text)) return "Storage";
  if (/(sql|cosmos|database|rds|aurora|dynamo|spanner|firestore|cache|redis)/.test(text)) return "Database";
  if (/(bandwidth|network|vnet|vpc|gateway|load balancer|elb|cdn|\bip\b|nat|dns)/.test(text)) return "Network";
  if (/(key vault|iam|security|firewall|sentinel|secret)/.test(text)) return "Security";
  if (/(synapse|bigquery|analytics|databricks|monitor|logging)/.test(text)) return "Analytics";
  return "Other";
}

export function kindSwatch(kind: string): Swatch {
  if (kind.startsWith("tag:")) {
    return { hex: "#2ee6c7", chip: "bg-teal-400/15 text-teal-200 border-teal-400/30", label: kind.slice(4) };
  }
  return KIND[kind] || KIND.resource;
}

export function categorySwatch(category: string, service = ""): Swatch {
  const name = category && CATEGORY[category] ? category : classifyCategory(service);
  return CATEGORY[name] || CATEGORY.Other;
}

export function seriesColor(kind?: string, category?: string, service?: string) {
  if (kind === "resource") return categorySwatch(category || "", service || "").hex;
  if (kind) return kindSwatch(kind).hex;
  return categorySwatch(category || "", service || "").hex;
}

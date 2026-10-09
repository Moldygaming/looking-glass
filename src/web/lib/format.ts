export function money(value: number, currency = "GBP") {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

export function moneyExact(value: number, currency = "GBP") {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}

export function compact(value: number) {
  return new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

export function moneyAxis(value: number, currency = "GBP") {
  return new Intl.NumberFormat("en-GB", {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

export function chartPeriodLabel(iso: string, granularity: string) {
  const date = (iso || "").slice(0, 10);
  const [, month, day] = date.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const mon = names[Number(month) - 1] || month || "";
  if (granularity === "month") return mon;
  return `${Number(day) || day} ${mon}`;
}

export function shortChartName(label: string, max = 28) {
  const parts = String(label || "")
    .split(/[\\/·]+/)
    .map((part) => part.trim())
    .filter(Boolean);
  const last = parts[parts.length - 1] || label || "Series";
  return last.length > max ? `${last.slice(0, max - 1)}…` : last;
}

export function tickStep(count: number, maxTicks = 7) {
  if (count <= maxTicks) return 0;
  return Math.ceil(count / maxTicks) - 1;
}

export function pct(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

export function periodLabel(iso: string, granularity: string) {
  const date = iso.slice(0, 10);
  if (granularity === "month") {
    const [year, month] = date.split("-");
    const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${names[Number(month) - 1] || month} ${year}`;
  }
  if (granularity === "week") return `Week of ${date}`;
  return date;
}

export function kindLabel(kind: string) {
  if (kind.startsWith("tag:")) return `Tag · ${kind.slice(4)}`;
  const labels: Record<string, string> = {
    provider: "Cloud",
    connection: "Connection",
    org: "Organisation",
    management_group: "Organisation",
    account: "Account",
    subscription: "Account",
    project: "Account",
    resource_group: "Resource group",
    region: "Region",
    category: "Category",
    service: "Service",
    resource_type: "Resource type",
    meter: "Meter",
    resource: "Resource",
  };
  return labels[kind] || kind.replaceAll("_", " ");
}

export function grainNoun(granularity: string, plural = false) {
  if (granularity === "week") return plural ? "weeks" : "week";
  if (granularity === "month") return plural ? "months" : "month";
  return plural ? "days" : "day";
}

export function when(iso?: string | null) {
  if (!iso) return "Never";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ageDays(iso?: string | null, fallback?: number | null) {
  if (typeof fallback === "number") return fallback;
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - date.getTime()) / 86400000));
}

export function ageLabel(days?: number | null) {
  if (days === null || days === undefined) return "—";
  if (days <= 0) return "today";
  if (days === 1) return "1 day";
  return `${days} days`;
}

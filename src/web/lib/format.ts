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
  const labels: Record<string, string> = {
    management_group: "Management group",
    subscription: "Subscription",
    account: "AWS account",
    project: "GCP project",
    resource_group: "Resource group",
    resource: "Resource",
    connection: "Connection",
  };
  return labels[kind] || kind;
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

export function KpiCard({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const color =
    tone === "good" ? "text-glass" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-rose" : "text-white";
  return (
    <div className="panel-pad">
      <div className="text-xs uppercase tracking-[0.16em] text-mist-500">{label}</div>
      <div className={`mt-2 font-mono text-2xl font-medium ${color}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-mist-400">{hint}</div>}
    </div>
  );
}

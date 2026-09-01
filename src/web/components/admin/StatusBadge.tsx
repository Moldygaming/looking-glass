export function StatusBadge({ status }: { status: string }) {
  const active = status === "active";
  return (
    <span className={`chip ${active ? "text-glass" : "text-rose"}`}>{active ? "Active" : "Disabled"}</span>
  );
}

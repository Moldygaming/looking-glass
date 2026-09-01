import { kindLabel } from "@/lib/format";
import { categorySwatch, kindSwatch } from "@/lib/colors";

export function KindBadge({ kind }: { kind: string }) {
  const swatch = kindSwatch(kind);
  return <span className={`chip ${swatch.chip}`}>{kindLabel(kind)}</span>;
}

export function CategoryBadge({ category, service }: { category?: string; service?: string }) {
  const swatch = categorySwatch(category || "", service || "");
  return <span className={`chip ${swatch.chip}`}>{swatch.label}</span>;
}

export function ColorDot({ hex, className = "" }: { hex: string; className?: string }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${className}`}
      style={{ background: hex, boxShadow: `0 0 8px ${hex}55` }}
    />
  );
}

export function ColorLegend({
  items,
}: {
  items: { hex: string; chip: string; label: string }[];
}) {
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {items.map((item) => (
        <span key={item.label} className={`chip ${item.chip}`}>
          <ColorDot hex={item.hex} className="mr-1.5" />
          {item.label}
        </span>
      ))}
    </div>
  );
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { ProviderBadge } from "@/components/ProviderBadge";
import { CategoryBadge, ColorDot, ColorLegend, KindBadge } from "@/components/TypeBadge";
import { CATEGORY_LEGEND, KIND_LEGEND, categorySwatch, kindSwatch } from "@/lib/colors";
import { moneyExact, pct } from "@/lib/format";
import type { HierarchyNode } from "@/lib/types";

function collectKeys(nodes: HierarchyNode[]): string[] {
  return nodes.flatMap((node) => [node.key, ...collectKeys(node.children || [])]);
}

export function HierarchyTree({
  nodes,
  selected,
  onToggle,
  currentLabel,
  previousLabel,
}: {
  nodes: HierarchyNode[];
  selected: string[];
  onToggle: (key: string) => void;
  currentLabel: string;
  previousLabel: string;
}) {
  const allKeys = useMemo(() => collectKeys(nodes), [nodes]);
  const [expanded, setExpanded] = useState<string[]>([]);
  useEffect(() => {
    setExpanded(nodes.flatMap((node) => [node.key, ...node.children.map((child) => child.key)]));
  }, [nodes]);

  function toggleOpen(key: string) {
    setExpanded((current) => (current.includes(key) ? current.filter((item) => item !== key) : [...current, key]));
  }

  if (!nodes.length) {
    return <p className="py-8 text-center text-sm text-mist-500">No hierarchical cost data in this period.</p>;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-mist-500">
          <tr>
            <th className="pb-2 w-8"></th>
            <th className="pb-2">Scope</th>
            <th className="pb-2">Type</th>
            <th className="pb-2">Workload</th>
            <th className="pb-2 text-right">{currentLabel}</th>
            <th className="pb-2 text-right">{previousLabel}</th>
            <th className="pb-2 text-right">Growth</th>
          </tr>
        </thead>
        <tbody>
          {nodes.map((node) => (
            <TreeRows
              key={node.key}
              node={node}
              depth={0}
              expanded={expanded}
              selected={selected}
              onToggle={onToggle}
              onOpen={toggleOpen}
            />
          ))}
        </tbody>
      </table>
      {allKeys.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-xs uppercase tracking-[0.16em] text-mist-500">Hierarchy</p>
          <ColorLegend items={KIND_LEGEND.map(([, swatch]) => swatch)} />
          <p className="pt-1 text-xs uppercase tracking-[0.16em] text-mist-500">Resource types</p>
          <ColorLegend items={CATEGORY_LEGEND} />
        </div>
      )}
    </div>
  );
}

function TreeRows({
  node,
  depth,
  expanded,
  selected,
  onToggle,
  onOpen,
}: {
  node: HierarchyNode;
  depth: number;
  expanded: string[];
  selected: string[];
  onToggle: (key: string) => void;
  onOpen: (key: string) => void;
}) {
  const children = node.children || [];
  const open = expanded.includes(node.key);
  const checked = selected.includes(node.key);
  const growthTone =
    node.delta_pct == null ? "text-mist-500" : node.delta_pct > 8 ? "text-rose" : node.delta_pct < 0 ? "text-glass" : "text-mist-100";
  const accent =
    node.kind === "resource" ? categorySwatch(node.category || "", node.service || "").hex : kindSwatch(node.kind).hex;
  return (
    <>
      <tr className={`border-t border-white/5 ${checked ? "bg-glass/5" : "hover:bg-white/5"}`}>
        <td className="py-2">
          <input type="checkbox" className="accent-glass" checked={checked} readOnly onClick={() => onToggle(node.key)} />
        </td>
        <td className="py-2">
          <div className="flex items-center gap-2" style={{ paddingLeft: depth * 18 }}>
            {children.length ? (
              <button type="button" className="text-mist-400" onClick={() => onOpen(node.key)}>
                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
              </button>
            ) : (
              <span className="inline-block w-3.5" />
            )}
            <ColorDot hex={accent} />
            <ProviderBadge provider={node.provider} />
            <button type="button" className="text-left" onClick={() => onToggle(node.key)}>
              {node.label}
            </button>
          </div>
        </td>
        <td>
          <KindBadge kind={node.kind} />
        </td>
        <td>{node.kind === "resource" ? <CategoryBadge category={node.category} service={node.service} /> : <span className="text-mist-500">—</span>}</td>
        <td className="text-right font-mono">{moneyExact(node.cost, node.currency)}</td>
        <td className="text-right font-mono text-mist-400">{moneyExact(node.prior_cost, node.currency)}</td>
        <td className={`text-right font-mono ${growthTone}`}>{node.delta_pct == null ? "—" : pct(node.delta_pct)}</td>
      </tr>
      {open &&
        children.map((child) => (
          <TreeRows
            key={child.key}
            node={child}
            depth={depth + 1}
            expanded={expanded}
            selected={selected}
            onToggle={onToggle}
            onOpen={onOpen}
          />
        ))}
    </>
  );
}

"use client";

import { ChevronRight, X } from "lucide-react";
import { kindLabel } from "@/lib/format";
import type { CostDimension, HierarchyPreset } from "@/lib/types";

export function PathBuilder({
  path,
  dimensions,
  presets,
  onChange,
}: {
  path: string[];
  dimensions: CostDimension[];
  presets: HierarchyPreset[];
  onChange: (next: string[]) => void;
}) {
  const used = new Set(path);
  const available = dimensions.filter((item) => !used.has(item.key));
  const grouped = new Map<string, CostDimension[]>();
  for (const item of available) {
    const list = grouped.get(item.group) || [];
    list.push(item);
    grouped.set(item.group, list);
  }

  function move(index: number, delta: number) {
    const next = index + delta;
    if (next < 0 || next >= path.length) return;
    const copy = [...path];
    [copy[index], copy[next]] = [copy[next], copy[index]];
    onChange(copy);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <select
          className="input max-w-xs"
          value=""
          onChange={(e) => {
            const id = e.target.value;
            const preset = presets.find((item) => item.id === id);
            if (preset?.path.length) onChange(preset.path);
          }}
        >
          <option value="">Hierarchy preset…</option>
          {presets.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {preset.name}
            </option>
          ))}
        </select>
        <p className="text-xs text-mist-500">Stack dimensions from coarse to fine. Drill into any level.</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {path.map((kind, index) => (
          <div key={`${kind}-${index}`} className="flex items-center gap-1">
            {index > 0 && <ChevronRight size={12} className="text-mist-500" />}
            <span className="inline-flex items-center gap-1 rounded-full border border-white/10 bg-white/5 px-2 py-1 text-xs text-mist-100">
              <button type="button" className="px-0.5 text-mist-500 hover:text-mist-100" onClick={() => move(index, -1)} disabled={index === 0}>
                ‹
              </button>
              {kindLabel(kind)}
              <button
                type="button"
                className="px-0.5 text-mist-500 hover:text-mist-100"
                onClick={() => move(index, 1)}
                disabled={index === path.length - 1}
              >
                ›
              </button>
              <button
                type="button"
                className="text-mist-500 hover:text-rose"
                onClick={() => onChange(path.filter((_, i) => i !== index))}
                disabled={path.length <= 1}
              >
                <X size={12} />
              </button>
            </span>
          </div>
        ))}
        {available.length > 0 && (
          <select
            className="input max-w-[220px] py-1 text-xs"
            value=""
            onChange={(e) => {
              if (e.target.value) onChange([...path, e.target.value]);
            }}
          >
            <option value="">+ dimension</option>
            {Array.from(grouped.entries()).map(([group, items]) => (
              <optgroup key={group} label={group}>
                {items.map((item) => (
                  <option key={item.key} value={item.key}>
                    {item.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        )}
      </div>
    </div>
  );
}

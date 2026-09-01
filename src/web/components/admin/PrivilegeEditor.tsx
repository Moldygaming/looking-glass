"use client";

import type { PrivilegeDef } from "@/lib/types";

export function PrivilegeEditor({
  catalog,
  selected,
  onChange,
  disabled,
  lockedKeys = [],
}: {
  catalog: PrivilegeDef[];
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  lockedKeys?: string[];
}) {
  const grouped = groupByModule(catalog);
  const selectedSet = new Set(selected);
  const hasAdmin = selectedSet.has("platform.admin");

  function toggle(key: string) {
    if (disabled || lockedKeys.includes(key)) return;
    if (selectedSet.has(key)) {
      onChange(selected.filter((item) => item !== key));
    } else {
      onChange([...selected, key]);
    }
  }

  function toggleModule(module: string, keys: string[]) {
    if (disabled) return;
    const unlocked = keys.filter((key) => !lockedKeys.includes(key));
    const allOn = unlocked.every((key) => selectedSet.has(key));
    if (allOn) {
      const drop = new Set(unlocked);
      onChange(selected.filter((key) => !drop.has(key)));
    } else {
      onChange(Array.from(new Set([...selected, ...unlocked])));
    }
  }

  return (
    <div className="space-y-4">
      {hasAdmin && (
        <p className="rounded-xl border border-glass/30 bg-glass/5 px-3 py-2 text-sm text-mist-300">
          <span className="font-medium text-glass">platform.admin</span> bypasses every other privilege and every data
          scope.
        </p>
      )}
      {grouped.map(([module, items]) => {
        const keys = items.map((item) => item.key);
        const unlocked = keys.filter((key) => !lockedKeys.includes(key));
        const onCount = keys.filter((key) => selectedSet.has(key)).length;
        return (
          <section key={module} className="rounded-xl border border-white/10 bg-ink-950/40">
            <div className="flex items-center justify-between gap-3 border-b border-white/5 px-4 py-3">
              <div>
                <h3 className="text-sm font-medium">{module}</h3>
                <p className="text-xs text-mist-500">
                  {onCount} of {keys.length} granted
                </p>
              </div>
              {!disabled && unlocked.length > 0 && (
                <button className="text-xs text-glass" type="button" onClick={() => toggleModule(module, keys)}>
                  {unlocked.every((key) => selectedSet.has(key)) ? "Clear module" : "Grant module"}
                </button>
              )}
            </div>
            <ul className="divide-y divide-white/5">
              {items.map((item) => {
                const locked = lockedKeys.includes(item.key);
                const checked = selectedSet.has(item.key);
                return (
                  <li key={item.key}>
                    <label
                      className={`flex cursor-pointer items-start gap-3 px-4 py-3 ${
                        disabled || locked ? "cursor-not-allowed opacity-70" : "hover:bg-white/[0.03]"
                      }`}
                    >
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={checked}
                        disabled={disabled || locked}
                        onChange={() => toggle(item.key)}
                      />
                      <span>
                        <span className="block text-sm text-mist-100">{item.name}</span>
                        <span className="mt-0.5 block font-mono text-[11px] text-glass/80">{item.key}</span>
                        <span className="mt-1 block text-xs text-mist-500">{item.description}</span>
                        {locked && <span className="mt-1 block text-[11px] uppercase tracking-wide text-warn">Locked</span>}
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function groupByModule(catalog: PrivilegeDef[]) {
  const map = new Map<string, PrivilegeDef[]>();
  for (const item of catalog) {
    const list = map.get(item.module) || [];
    list.push(item);
    map.set(item.module, list);
  }
  return Array.from(map.entries());
}

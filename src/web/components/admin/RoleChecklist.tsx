"use client";

import type { AccessRole, RoleRef } from "@/lib/types";

export function RoleChecklist({
  roles,
  selected,
  onChange,
  disabled,
  lockedIds = [],
}: {
  roles: Array<AccessRole | RoleRef>;
  selected: string[];
  onChange: (next: string[]) => void;
  disabled?: boolean;
  lockedIds?: string[];
}) {
  const selectedSet = new Set(selected);

  function toggle(id: string) {
    if (disabled || lockedIds.includes(id)) return;
    if (selectedSet.has(id)) onChange(selected.filter((item) => item !== id));
    else onChange([...selected, id]);
  }

  if (!roles.length) {
    return <p className="text-sm text-mist-500">No roles yet. Create one under Admin → Roles.</p>;
  }

  return (
    <ul className="divide-y divide-white/5 rounded-xl border border-white/10 bg-ink-950/40">
      {roles.map((role) => {
        const locked = lockedIds.includes(role.id);
        const privileges = "privileges" in role ? role.privileges : undefined;
        const description = "description" in role ? role.description : undefined;
        return (
          <li key={role.id}>
            <label
              className={`flex cursor-pointer items-start gap-3 px-4 py-3 ${
                disabled || locked ? "cursor-not-allowed opacity-70" : "hover:bg-white/[0.03]"
              }`}
            >
              <input
                type="checkbox"
                className="mt-1"
                checked={selectedSet.has(role.id)}
                disabled={disabled || locked}
                onChange={() => toggle(role.id)}
              />
              <span>
                <span className="flex items-center gap-2 text-sm text-mist-100">
                  {role.name}
                  {role.is_system && <span className="chip text-glass">System</span>}
                </span>
                {description && <span className="mt-1 block text-xs text-mist-500">{description}</span>}
                {privileges && (
                  <span className="mt-1 block font-mono text-[11px] text-mist-500">
                    {privileges.length
                      ? privileges.includes("platform.admin")
                        ? "platform.admin"
                        : privileges.join(", ")
                      : "No permissions yet"}
                  </span>
                )}
                {locked && <span className="mt-1 block text-[11px] uppercase tracking-wide text-warn">Locked</span>}
              </span>
            </label>
          </li>
        );
      })}
    </ul>
  );
}

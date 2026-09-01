import type { Me } from "./types";

export function hasPrivilege(me: Me | null | undefined, ...keys: string[]) {
  if (!me) return false;
  if (me.is_admin || me.privileges.includes("platform.admin")) return true;
  return keys.some((key) => me.privileges.includes(key));
}

export function canAccessAdmin(me: Me | null | undefined) {
  if (!me) return false;
  return me.is_admin || me.privileges.some((key) => key.startsWith("admin."));
}

export function sourceLabel(kind: string, via?: string | null) {
  if (kind === "implied") return "Implied";
  if (kind === "role" && via === "direct") return "Role (direct)";
  if (kind === "role") return "Role";
  return kind;
}

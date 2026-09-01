export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const isServer = typeof window === "undefined";
  let url = `/api/lg${path}`;
  const headers: Record<string, string> = {
    "content-type": "application/json",
  };

  if (isServer) {
    const { auth } = await import("@/auth");
    const session = await auth();
    url = `${process.env.API_URL || "http://localhost:8000"}${path}`;
    headers["X-Internal-Key"] = process.env.INTERNAL_API_KEY || "";
    headers["X-User-Oid"] = session?.user?.id || "";
    headers["X-User-Email"] = session?.user?.email || "";
    headers["X-User-Name"] = session?.user?.name || "";
    headers["X-User-Roles"] = (session?.user?.roles || []).join(",");
    headers["X-User-Groups"] = (session?.user?.groups || []).join(",");
  }

  if (init?.headers) {
    Object.assign(headers, init.headers as Record<string, string>);
  }

  const res = await fetch(url, { ...init, headers, cache: "no-store" });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(_errorMessage(text, res.status, res.statusText));
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function _errorMessage(text: string, status: number, statusText: string) {
  if (!text) return `${status} ${statusText}`;
  try {
    const body = JSON.parse(text) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail
        .map((item) => (typeof item === "object" && item && "msg" in item ? String(item.msg) : JSON.stringify(item)))
        .join("; ");
    }
  } catch {
    return text;
  }
  return text;
}

export function qs(params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

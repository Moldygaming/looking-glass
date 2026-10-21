import { getToken } from "next-auth/jwt";
import { NextRequest, NextResponse } from "next/server";

const API_TIMEOUT_MS = 60_000;

function textList(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

async function proxy(req: NextRequest, path: string[]) {
  const secureCookie = req.cookies
    .getAll()
    .some((cookie) => cookie.name.startsWith("__Secure-authjs.session-token"));
  const token = await getToken({
    req,
    secret: process.env.AUTH_SECRET,
    secureCookie,
  });
  const oid = String(token?.oid || token?.sub || "");
  if (!token || !oid) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const base = process.env.API_URL || "http://127.0.0.1:8000";
  const target = `${base}/${path.join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = {
    "X-Internal-Key": process.env.INTERNAL_API_KEY || "",
    "X-User-Oid": oid,
    "X-User-Email": token.email ? String(token.email) : "",
    "X-User-Name": token.name ? String(token.name) : "",
    "X-User-Roles": textList(token.roles).join(","),
    "X-User-Groups": textList(token.groups).join(","),
  };
  const contentType = req.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  try {
    const res = await fetch(target, {
      method: req.method,
      headers,
      body: hasBody ? await req.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(API_TIMEOUT_MS),
    });
    const body = await res.arrayBuffer();
    return new NextResponse(body, {
      status: res.status,
      headers: { "content-type": res.headers.get("content-type") || "application/json" },
    });
  } catch {
    return NextResponse.json(
      { detail: "The API did not respond. Check API_URL from the web container." },
      { status: 504 }
    );
  }
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path);
}
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  return proxy(req, (await ctx.params).path);
}

import { auth } from "@/auth";
import { NextRequest, NextResponse } from "next/server";

async function proxy(req: NextRequest, path: string[]) {
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ detail: "unauthorized" }, { status: 401 });
  }
  const target = `${process.env.API_URL || "http://localhost:8000"}/${path.join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = {
    "X-Internal-Key": process.env.INTERNAL_API_KEY || "",
    "X-User-Oid": session.user.id,
    "X-User-Email": session.user.email || "",
    "X-User-Name": session.user.name || "",
    "X-User-Roles": (session.user.roles || []).join(","),
    "X-User-Groups": (session.user.groups || []).join(","),
  };
  const contentType = req.headers.get("content-type");
  if (contentType) headers["content-type"] = contentType;
  const hasBody = !["GET", "HEAD"].includes(req.method);
  const res = await fetch(target, {
    method: req.method,
    headers,
    body: hasBody ? await req.text() : undefined,
    cache: "no-store",
  });
  const body = await res.arrayBuffer();
  return new NextResponse(body, {
    status: res.status,
    headers: { "content-type": res.headers.get("content-type") || "application/json" },
  });
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

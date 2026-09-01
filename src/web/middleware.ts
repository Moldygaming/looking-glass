import { auth } from "@/auth";
import { NextResponse } from "next/server";

export default auth((req) => {
  const path = req.nextUrl.pathname;
  const publicPath =
    path.startsWith("/login") ||
    path.startsWith("/api/auth") ||
    path.startsWith("/api/config") ||
    path.startsWith("/_next") ||
    path === "/favicon.ico";
  if (!req.auth && !publicPath) {
    const login = new URL("/login", req.nextUrl.origin);
    login.searchParams.set("callbackUrl", path);
    return NextResponse.redirect(login);
  }
  if (req.auth && path === "/login") {
    return NextResponse.redirect(new URL("/", req.nextUrl.origin));
  }
  return NextResponse.next();
});

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};

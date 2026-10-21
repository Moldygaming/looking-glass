import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Cookie presence only. Importing auth() pulls the Entra callback into the
// middleware worker, and that worker's response stream times out after
// Microsoft redirects back. The Node auth route and /api/lg still verify the JWT.
const SESSION_COOKIES = ["authjs.session-token", "__Secure-authjs.session-token"];

function hasSessionCookie(req: NextRequest): boolean {
  return req.cookies.getAll().some((cookie) =>
    SESSION_COOKIES.some((name) => cookie.name === name || cookie.name.startsWith(`${name}.`))
  );
}

export function middleware(req: NextRequest) {
  const path = req.nextUrl.pathname;
  const signedIn = hasSessionCookie(req);
  if (path === "/login") {
    if (!signedIn) return NextResponse.next();
    return NextResponse.redirect(new URL("/", req.nextUrl.origin));
  }
  if (!signedIn) {
    const login = new URL("/login", req.nextUrl.origin);
    login.searchParams.set("callbackUrl", path);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/auth|api/config|_next/static|_next/image|favicon.ico|favicon.svg).*)"],
};

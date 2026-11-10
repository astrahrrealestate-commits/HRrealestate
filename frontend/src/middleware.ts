import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

export function middleware(request: NextRequest) {
  const sessionCookie = request.cookies.get("eo_session");
  const { pathname } = request.nextUrl;

  // 1. Always allow Next.js internals, static files, and API endpoints
  if (
    pathname.startsWith("/_next") ||
    pathname.startsWith("/api") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  // 2. If session token is in URL (from Google OAuth callback redirect), set cookie on localhost:3000
  const urlToken = request.nextUrl.searchParams.get("session_token");
  if (urlToken) {
    const response = NextResponse.next();
    response.cookies.set("eo_session", urlToken, {
      path: "/",
      httpOnly: true,
      sameSite: "lax",
    });
    return response;
  }

  // 3. If user already has a valid session and visits /login, redirect to dashboard
  if (pathname === "/login") {
    if (sessionCookie && sessionCookie.value) {
      return NextResponse.redirect(new URL("/", request.url));
    }
    return NextResponse.next();
  }

  // 4. Protected routes: If no session cookie, redirect to /login
  if (!sessionCookie || !sessionCookie.value) {
    const loginUrl = new URL("/login", request.url);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match all request paths except:
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico, sitemap.xml, robots.txt
     */
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};


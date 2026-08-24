import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/auth", "/setup", "/invite"];

// Same default as lib/api/client.ts — without it, an unset BACKEND_URL makes
// the verify fetch throw on every request and bounces signed-in users to /auth.
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

export async function proxy(request: NextRequest) {
	const { pathname } = request.nextUrl;
	const accessToken = request.cookies.get("access_token")?.value;
	const isPublicPath = PUBLIC_PATHS.some((path) => pathname.startsWith(path));

	// Router prefetches (Next 16 issues two per visible <Link>: a route-tree
	// request and a segment request) would each pay a blocking backend
	// round-trip here. They only warm the client cache — the real navigation
	// still gets verified, and the backend authenticates every data call — so
	// let them through unverified. Accepted trade-off: with an expired or
	// revoked token, a prefetched server render's backend calls 401 and the
	// prefetch is discarded; no protected data is served, and the actual
	// navigation still redirects to /auth and clears the cookie.
	const isPrefetch =
		request.headers.has("next-router-prefetch") ||
		request.headers.has("next-router-segment-prefetch");
	if (accessToken && isPrefetch && !isPublicPath) {
		return NextResponse.next();
	}

	if (accessToken) {
		try {
			const verifyRes = await fetch(`${BACKEND_URL}/auth/me`, {
				headers: { Cookie: `access_token=${accessToken}` },
			});

			if (verifyRes.ok) {
				if (isPublicPath) {
					return NextResponse.redirect(new URL("/agents", request.url));
				}
				return NextResponse.next();
			}
		} catch (err) {
			console.error("Backend unreachable or validation failed", err);
		}

		const response = NextResponse.redirect(new URL("/auth", request.url));
		response.cookies.delete("access_token");
		return response;
	}

	if (!isPublicPath) {
		return NextResponse.redirect(new URL("/auth", request.url));
	}

	return NextResponse.next();
}

export const config = {
	matcher: [
		/*
		 * Match all request paths except:
		 * - api routes
		 * - _next/static (static files)
		 * - _next/image (image optimization)
		 * - static assets (any path with a file extension, e.g. logo.svg)
		 */
		"/((?!api|_next/static|_next/image|.*\\..*).*)",
	],
};

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = [
	"/auth",
	"/setup",
	"/invite",
	"/forgot-password",
	"/reset-password",
];
const ALWAYS_PUBLIC_PATHS = ["/share"];
const PUBLIC_MCP_ENDPOINTS = new Set([
	"/mcp",
	"/register",
	"/authorize",
	"/token",
	"/revoke",
]);

// Same default as lib/api/client.ts — without it, an unset BACKEND_URL makes
// the verify fetch throw on every request and bounces signed-in users to /auth.
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

function isPathWithin(pathname: string, root: string): boolean {
	return pathname === root || pathname.startsWith(`${root}/`);
}

function oauthReturnTo(value: string | null): string | null {
	if (!value || !value.startsWith("/") || value.startsWith("//")) return null;
	try {
		const target = new URL(value, "http://auxilia.local");
		if (
			target.origin !== "http://auxilia.local" ||
			target.pathname !== "/mcp/authorize"
		) {
			return null;
		}
		return `${target.pathname}${target.search}`;
	} catch {
		return null;
	}
}

function safeNext(value: string | null): string | null {
	return value && /^\/(?![/\\])[^\t\n\r]*$/.test(value) ? value : null;
}

function authRedirect(request: NextRequest): NextResponse {
	const returnTo =
		request.nextUrl.pathname === "/mcp/authorize"
			? `${request.nextUrl.pathname}${request.nextUrl.search}`
			: null;
	const url = new URL("/auth", request.url);
	if (returnTo) {
		url.searchParams.set("returnTo", returnTo);
	} else if (
		request.nextUrl.pathname !== "/" &&
		!PUBLIC_PATHS.some((path) => isPathWithin(request.nextUrl.pathname, path))
	) {
		url.searchParams.set(
			"next",
			`${request.nextUrl.pathname}${request.nextUrl.search}`,
		);
	}
	return NextResponse.redirect(url);
}

export async function proxy(request: NextRequest) {
	const { pathname } = request.nextUrl;
	if (
		PUBLIC_MCP_ENDPOINTS.has(pathname) ||
		pathname.startsWith("/.well-known/")
	) {
		return NextResponse.next();
	}
	const accessToken = request.cookies.get("access_token")?.value;
	const isAlwaysPublicPath = ALWAYS_PUBLIC_PATHS.some((path) =>
		isPathWithin(pathname, path),
	);
	if (isAlwaysPublicPath) {
		return NextResponse.next();
	}
	const isPublicPath = PUBLIC_PATHS.some((path) => isPathWithin(pathname, path));
	const isInvitePath = isPathWithin(pathname, "/invite");
	const isPasswordRecoveryPath =
		isPathWithin(pathname, "/forgot-password") ||
		isPathWithin(pathname, "/reset-password");

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
			const cookieHeader = request.headers.get("cookie");
			const verifyRes = await fetch(`${BACKEND_URL}/auth/me`, {
				headers: cookieHeader ? { Cookie: cookieHeader } : undefined,
			});

			if (verifyRes.ok) {
				// A signed-in user may still need to accept an invitation to
				// another workspace. Auth/setup pages are no longer useful once
				// authenticated, but invite pages must remain reachable.
				if (isPublicPath && !isInvitePath && !isPasswordRecoveryPath) {
					const returnTo = oauthReturnTo(
						request.nextUrl.searchParams.get("returnTo"),
					);
					if (returnTo) {
						return NextResponse.redirect(new URL(returnTo, request.url));
					}
					const next = safeNext(request.nextUrl.searchParams.get("next"));
					if (next) {
						return NextResponse.redirect(new URL(next, request.url));
					}
					return NextResponse.redirect(new URL("/", request.url));
				}
				return NextResponse.next();
			}
			if (verifyRes.status !== 401) {
				console.error(
					`Session validation failed with status ${verifyRes.status}`,
				);
				return NextResponse.next();
			}
		} catch (err) {
			console.error("Backend unreachable or validation failed", err);
			return NextResponse.next();
		}

		const response =
			isInvitePath || isPasswordRecoveryPath
				? NextResponse.next()
				: authRedirect(request);
		response.cookies.delete("access_token");
		response.cookies.delete("active_workspace_id");
		return response;
	}

	if (!isPublicPath) {
		return authRedirect(request);
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

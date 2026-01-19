import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/auth"];

export function middleware(request: NextRequest) {
	const { pathname } = request.nextUrl;
	const accessToken = request.cookies.get("access_token")?.value;

	const isPublicPath = PUBLIC_PATHS.some((path) => pathname.startsWith(path));

	// If user is not authenticated and trying to access protected route
	if (!accessToken && !isPublicPath) {
		const url = request.nextUrl.clone();
		url.pathname = "/auth";
		return NextResponse.redirect(url);
	}

	// If user is authenticated and trying to access auth page
	if (accessToken && isPublicPath) {
		const url = request.nextUrl.clone();
		url.pathname = "/agents";
		return NextResponse.redirect(url);
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
		 * - favicon.ico, sitemap.xml, robots.txt
		 */
		"/((?!api|_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
	],
};

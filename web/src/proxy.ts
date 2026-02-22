import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const PUBLIC_PATHS = ["/auth", "/setup", "/invite"];

export async function proxy(request: NextRequest) {
	const { pathname } = request.nextUrl;
	const accessToken = request.cookies.get("access_token")?.value;
	const isPublicPath = PUBLIC_PATHS.some((path) => pathname.startsWith(path));
	if (accessToken) {
		try {
			const verifyRes = await fetch(`${process.env.BACKEND_URL}/auth/me`, {
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
		 * - favicon.ico, sitemap.xml, robots.txt
		 */
		"/((?!api|_next/static|_next/image|favicon.ico|sitemap.xml|robots.txt).*)",
	],
};

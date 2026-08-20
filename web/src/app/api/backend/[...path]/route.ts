import { NextRequest } from "next/server";

const getBackendUrl = () => process.env.BACKEND_URL || "http://localhost:8000";

async function proxyRequest(
	request: NextRequest,
	context: { params: Promise<{ path: string[] }> },
) {
	const { path } = await context.params;
	let pathSegment = Array.isArray(path) ? path.join("/") : path;
	// FastAPI returns 307 for POST /mcp-servers → /mcp-servers/; avoid redirect by
	// adding trailing slash for single-segment (collection) paths.
	if (path.length === 1 && !pathSegment.endsWith("/")) {
		pathSegment += "/";
	}
	const url = `${getBackendUrl()}/${pathSegment}${request.nextUrl.search}`;
	const headers = new Headers(request.headers);
	headers.delete("host");

	const response = await fetch(url, {
		method: request.method,
		headers,
		body: request.body,
		redirect: "manual",
		// @ts-expect-error - duplex is required for streaming bodies
		duplex: "half",
	});

	// fetch already decoded any Content-Encoding on the backend response, so
	// the encoding headers describe a body we no longer have — forwarding
	// them makes the browser try to gunzip plain JSON and fail every call.
	const responseHeaders = new Headers(response.headers);
	responseHeaders.delete("content-encoding");
	responseHeaders.delete("content-length");

	return new Response(response.body, {
		status: response.status,
		headers: responseHeaders,
	});
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;

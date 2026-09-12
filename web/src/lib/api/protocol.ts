import { API_BASE_URL } from "@/lib/api/client";

/**
 * The raw transport for LangGraph-shaped payloads — the Agent Streaming
 * Protocol endpoints (`/threads/{id}/state`, `/history`, `/stream/events`,
 * `/commands`) and whole-message reads (`/threads/{id}/messages/{id}`).
 *
 * These bodies are the SDK's own wire format (snake_case keys, arbitrary tool
 * payloads) and must reach it untouched, so they bypass the axios client and
 * its case conversion. Everything that talks to these endpoints goes through
 * `protocolFetch`; nothing else hand-builds a URL with `credentials: "include"`.
 */

/** Absolute base URL for `useStream({ apiUrl })` — the SDK needs an absolute URL. */
export function protocolApiUrl(): string {
	if (typeof window === "undefined") return API_BASE_URL;
	return new URL(API_BASE_URL, window.location.origin).toString();
}

function currentOrigin(): string {
	return typeof window === "undefined" ? "" : window.location.origin;
}

/**
 * Resolve a request target against the page origin and refuse anything
 * cross-origin — the cookie session must never be sent elsewhere.
 */
export function resolveSameOriginUrl(input: RequestInfo | URL): string {
	const raw =
		typeof input === "string"
			? input
			: input instanceof URL
				? input.href
				: input.url;
	const origin = currentOrigin();
	const parsed = origin ? new URL(raw, origin) : null;
	if (parsed == null || parsed.origin !== origin) {
		throw new Error(`Blocked non-same-origin request: ${raw}`);
	}
	return `${origin}${parsed.pathname}${parsed.search}`;
}

/**
 * Same-origin `fetch` with the session cookie. No case conversion. A `Request`
 * input is reproduced (method, headers, body, signal and the other fetch
 * options) with only its URL re-pinned; `credentials` is always `include`.
 */
export const protocolFetch: typeof fetch = async (input, init) => {
	const url = resolveSameOriginUrl(input);
	const fromRequest = input instanceof Request ? await requestInit(input) : {};
	// The URL was just rebuilt from the page origin + the request's path and
	// query (`resolveSameOriginUrl` throws on any other origin), so this is
	// not a user-controlled destination.
	// nosemgrep
	return fetch(url, { credentials: "include", ...fromRequest, ...init });
};

/** Everything of a `Request` that `fetch(url, init)` needs to reproduce it.
 *  (`new Request(url, request)` does not copy these: a Request is not a
 *  RequestInit dictionary.) The body is buffered — protocol commands are
 *  small JSON — so no streaming-body constraints apply. `credentials` is
 *  deliberately not copied: this transport always sends the session cookie. */
async function requestInit(request: Request): Promise<RequestInit> {
	const hasBody = request.method !== "GET" && request.method !== "HEAD";
	return {
		method: request.method,
		headers: request.headers,
		body: hasBody ? await request.clone().arrayBuffer() : undefined,
		signal: request.signal,
		redirect: request.redirect,
		mode: request.mode,
		cache: request.cache,
		referrer: request.referrer,
		referrerPolicy: request.referrerPolicy,
		integrity: request.integrity,
		keepalive: request.keepalive,
	};
}

/**
 * The JSON-RPC-style `method` of a protocol command body (`run.start`,
 * `input.respond`, …), or `undefined` when the body is not such a command.
 */
export function protocolCommandMethod(init?: RequestInit): string | undefined {
	if (typeof init?.body !== "string") return undefined;
	try {
		const method = (JSON.parse(init.body) as { method?: unknown }).method;
		return typeof method === "string" ? method : undefined;
	} catch {
		return undefined;
	}
}

export type ProtocolRejection =
	| { kind: "model_unavailable"; detail: string }
	| { kind: "stale_interrupt"; detail: string };

const REJECTION_DEFAULTS: Record<ProtocolRejection["kind"], string> = {
	model_unavailable:
		"This conversation's model is no longer available in this workspace.",
	stale_interrupt: "This approval was already handled elsewhere.",
};

/**
 * Decode the backend's pre-run 409 gates (`ModelUnavailableError`,
 * `StaleInterruptError` in `app/exceptions.py`) from a response status and
 * body. Anything else — a different status, an unknown `error` key, a
 * non-object body — is `null`: not a gate this client knows how to handle.
 */
export function decodeProtocolRejection(
	status: number,
	body: unknown,
): ProtocolRejection | null {
	if (status !== 409 || !body || typeof body !== "object") return null;
	const { error, detail } = body as { error?: unknown; detail?: unknown };
	if (error !== "model_unavailable" && error !== "stale_interrupt") return null;
	return {
		kind: error,
		detail: typeof detail === "string" ? detail : REJECTION_DEFAULTS[error],
	};
}

/** The `Error` the stream stack records for a decoded rejection. */
export function protocolRejectionError(rejection: ProtocolRejection): Error {
	const err = new Error(rejection.detail);
	err.name =
		rejection.kind === "model_unavailable"
			? "ModelUnavailableError"
			: "StaleInterruptError";
	return err;
}

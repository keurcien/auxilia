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

/** Same-origin `fetch` with the session cookie. No case conversion. */
export const protocolFetch: typeof fetch = (input, init) =>
	fetch(resolveSameOriginUrl(input), { credentials: "include", ...init });

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

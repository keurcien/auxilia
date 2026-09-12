import { afterEach, describe, expect, it, vi } from "vitest";

import {
	decodeProtocolRejection,
	protocolCommandMethod,
	protocolFetch,
	protocolRejectionError,
	resolveSameOriginUrl,
} from "./protocol";

afterEach(() => {
	vi.unstubAllGlobals();
});

describe("resolveSameOriginUrl", () => {
	it("resolves a relative path against the page origin", () => {
		expect(resolveSameOriginUrl("/api/backend/threads/t/state")).toBe(
			`${window.location.origin}/api/backend/threads/t/state`,
		);
	});

	it("accepts an absolute same-origin URL, string or URL or Request", () => {
		const abs = `${window.location.origin}/api/backend/x?y=1`;
		expect(resolveSameOriginUrl(abs)).toBe(abs);
		expect(resolveSameOriginUrl(new URL(abs))).toBe(abs);
		expect(resolveSameOriginUrl(new Request(abs))).toBe(abs);
	});

	it("refuses a cross-origin target", () => {
		expect(() => resolveSameOriginUrl("https://evil.example/api")).toThrow(
			/non-same-origin/,
		);
	});
});

describe("protocolFetch", () => {
	it("sends the session cookie and passes init through, without case conversion", async () => {
		const fetchMock = vi.fn().mockResolvedValue(new Response("{}"));
		vi.stubGlobal("fetch", fetchMock);
		const body = JSON.stringify({ method: "run.start", params: { tool_call_id: "c" } });
		await protocolFetch("/api/backend/threads/t/commands", { method: "POST", body });
		expect(fetchMock).toHaveBeenCalledWith(
			`${window.location.origin}/api/backend/threads/t/commands`,
			{ credentials: "include", method: "POST", body },
		);
	});
});

describe("protocolCommandMethod", () => {
	it("reads the command method from a JSON body", () => {
		expect(protocolCommandMethod({ body: JSON.stringify({ method: "run.start" }) })).toBe(
			"run.start",
		);
	});

	it("is undefined for no body, a non-string body, invalid JSON or no method", () => {
		expect(protocolCommandMethod(undefined)).toBeUndefined();
		expect(protocolCommandMethod({ body: new FormData() })).toBeUndefined();
		expect(protocolCommandMethod({ body: "{not json" })).toBeUndefined();
		expect(protocolCommandMethod({ body: JSON.stringify({ params: {} }) })).toBeUndefined();
	});
});

describe("decodeProtocolRejection", () => {
	it("decodes the two pre-run gates, with the backend detail", () => {
		expect(
			decodeProtocolRejection(409, {
				error: "model_unavailable",
				model_id: "m",
				detail: "disabled by an admin",
			}),
		).toEqual({ kind: "model_unavailable", detail: "disabled by an admin" });
		expect(decodeProtocolRejection(409, { error: "stale_interrupt", detail: "handled" })).toEqual(
			{ kind: "stale_interrupt", detail: "handled" },
		);
	});

	it("falls back to a default detail when the body has none", () => {
		const r = decodeProtocolRejection(409, { error: "model_unavailable" });
		expect(r?.kind).toBe("model_unavailable");
		expect(r?.detail).toMatch(/no longer available/);
	});

	it("is null for other statuses, unknown error keys and non-object bodies", () => {
		expect(decodeProtocolRejection(400, { error: "model_unavailable" })).toBeNull();
		expect(decodeProtocolRejection(409, { error: "something_else" })).toBeNull();
		expect(decodeProtocolRejection(409, { detail: "conflict" })).toBeNull();
		expect(decodeProtocolRejection(409, null)).toBeNull();
		expect(decodeProtocolRejection(409, "conflict")).toBeNull();
	});
});

describe("protocolRejectionError", () => {
	it("names the error after the gate so the stream stack can tell them apart", () => {
		expect(
			protocolRejectionError({ kind: "model_unavailable", detail: "d" }).name,
		).toBe("ModelUnavailableError");
		expect(protocolRejectionError({ kind: "stale_interrupt", detail: "d" }).name).toBe(
			"StaleInterruptError",
		);
		expect(protocolRejectionError({ kind: "stale_interrupt", detail: "d" }).message).toBe("d");
	});
});

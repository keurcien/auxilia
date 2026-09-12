import { AxiosError } from "axios";
import { describe, expect, it } from "vitest";

import { ApiError, getApiErrorMessage, isApiError, toApiError } from "./errors";

const axios4xx = (status: number, data: unknown) =>
	new AxiosError("boom", "ERR_BAD_REQUEST", undefined, undefined, {
		status,
		data,
		statusText: "",
		headers: {},
		config: { headers: {} } as never,
	});

describe("toApiError", () => {
	it("passes an ApiError through untouched", () => {
		const e = new ApiError({ status: 404, body: { detail: "gone" } });
		expect(toApiError(e)).toBe(e);
	});

	it("unwraps an AxiosError and keeps the original as cause", () => {
		const raw = axios4xx(403, { detail: "nope" });
		const e = toApiError(raw);
		expect(isApiError(e)).toBe(true);
		expect(e.status).toBe(403);
		expect(e.detail).toBe("nope");
		expect(e.cause).toBe(raw);
	});

	it("reads an axios-shaped plain object (what a test double rejects with)", () => {
		const e = toApiError({
			status: 409,
			response: { data: { detail: "already exists" } },
		});
		expect(e.status).toBe(409);
		expect(e.detail).toBe("already exists");
		expect(getApiErrorMessage(e, "fb")).toBe("already exists");
	});

	it("reads a rejection that only carries a top-level status", () => {
		const e = toApiError({ status: 403, message: "forbidden" });
		expect(e.status).toBe(403);
		expect(e.message).toBe("forbidden");
	});

	it("wraps anything else as a status-less error", () => {
		const e = toApiError(new TypeError("fetch failed"));
		expect(e.status).toBeNull();
		expect(e.detail).toBeNull();
		expect(e.message).toBe("fetch failed");
	});
});

describe("getApiErrorMessage", () => {
	it("trusts `detail` on 4xx", () => {
		expect(getApiErrorMessage(axios4xx(400, { detail: "bad name" }), "fb")).toBe(
			"bad name",
		);
		expect(
			getApiErrorMessage(new ApiError({ status: 409, body: { detail: "dup" } }), "fb"),
		).toBe("dup");
	});

	it("falls back on 5xx, blank detail, network errors and unknown shapes", () => {
		expect(getApiErrorMessage(axios4xx(500, { detail: "trace" }), "fb")).toBe("fb");
		expect(getApiErrorMessage(axios4xx(400, { detail: "   " }), "fb")).toBe("fb");
		expect(getApiErrorMessage(axios4xx(400, "not json"), "fb")).toBe("fb");
		expect(getApiErrorMessage(new Error("offline"), "fb")).toBe("fb");
		expect(getApiErrorMessage(undefined, "fb")).toBe("fb");
	});
});

import { describe, expect, it } from "vitest";
import { getApiErrorMessage } from "./errors";

const axiosError = (status: number, data: unknown) => ({ response: { status, data } });

describe("getApiErrorMessage", () => {
	it("uses a domain error's string detail", () => {
		expect(
			getApiErrorMessage(axiosError(400, { detail: "This repository is empty." }), "nope"),
		).toBe("This repository is empty.");
	});

	it("reads FastAPI's 422 validation array", () => {
		// The shape that made a rejected field look like nothing happened: the
		// old reader only understood `detail` as a string and fell through to
		// the caller's generic fallback.
		const detail = [
			{
				type: "value_error",
				loc: ["body", "url"],
				msg: "Value error, must be an https:// repository URL",
				input: "acme/skills",
			},
		];
		expect(getApiErrorMessage(axiosError(422, { detail }), "nope")).toBe(
			"must be an https:// repository URL",
		);
	});

	it("joins several fields and says each rule once", () => {
		const detail = [
			{ loc: ["body", "url"], msg: "Value error, must be an https:// repository URL" },
			{ loc: ["body", "ref"], msg: "Value error, must be an https:// repository URL" },
			{ loc: ["body", "name"], msg: "field required" },
		];
		expect(getApiErrorMessage(axiosError(422, { detail }), "nope")).toBe(
			"must be an https:// repository URL; field required",
		);
	});

	it("falls back for 5xx, for a network error, and for shapes it cannot read", () => {
		expect(getApiErrorMessage(axiosError(500, { detail: "boom" }), "fallback")).toBe("fallback");
		expect(getApiErrorMessage(new Error("Network Error"), "fallback")).toBe("fallback");
		expect(getApiErrorMessage(axiosError(400, { detail: [] }), "fallback")).toBe("fallback");
		expect(getApiErrorMessage(axiosError(400, { detail: [{ loc: ["x"] }] }), "fallback")).toBe(
			"fallback",
		);
	});
});

import { describe, expect, it } from "vitest";
import { extractToolErrorText, extractToolMessageText } from "./tool-content";

describe("extractToolMessageText", () => {
	it("returns a plain string content as-is", () => {
		expect(extractToolMessageText("boom")).toBe("boom");
	});

	it("returns undefined for an empty string", () => {
		expect(extractToolMessageText("")).toBeUndefined();
	});

	it("flattens a list of text content blocks (MCP error shape)", () => {
		const content = [
			{ type: "text", text: "Permission denied: " },
			{ type: "text", text: "insufficient scope" },
		];
		expect(extractToolMessageText(content)).toBe(
			"Permission denied: insufficient scope",
		);
	});

	it("ignores non-text blocks when flattening", () => {
		const content = [
			{ type: "image", data: "…" },
			{ type: "text", text: "real error" },
		];
		expect(extractToolMessageText(content)).toBe("real error");
	});

	it("returns undefined when no readable text is present", () => {
		expect(extractToolMessageText([{ type: "image", data: "…" }])).toBeUndefined();
		expect(extractToolMessageText(null)).toBeUndefined();
		expect(extractToolMessageText(undefined)).toBeUndefined();
	});
});

describe("extractToolErrorText", () => {
	it("surfaces the real error from a content-block list", () => {
		const content = [{ type: "text", text: "429 rate limited" }];
		expect(extractToolErrorText(content)).toBe("429 rate limited");
	});

	it("falls back to a generic message when there is no readable text", () => {
		expect(extractToolErrorText(null)).toBe("Tool execution failed");
		expect(extractToolErrorText([])).toBe("Tool execution failed");
	});
});

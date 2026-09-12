import { describe, expect, it } from "vitest";

import { promptMessageToContent } from "./build-content";

describe("promptMessageToContent", () => {
	it("is null for nothing to send", () => {
		expect(promptMessageToContent(null)).toBeNull();
		expect(promptMessageToContent({ text: "   ", files: [] })).toBeNull();
	});

	it("keeps text-only as a plain string", () => {
		expect(promptMessageToContent({ text: "hi there", files: [] })).toBe("hi there");
	});

	it("turns attachments into content blocks", () => {
		const content = promptMessageToContent({
			text: "look",
			files: [
				{ type: "file", url: "data:image/png;base64,AAA", mediaType: "image/png", filename: "a.png" },
				{ type: "file", url: "data:text/csv;base64,QkJC", mediaType: "text/csv", filename: "rows.csv" },
			],
		});
		expect(content).toEqual([
			{ type: "text", text: "look" },
			{ type: "image_url", image_url: { url: "data:image/png;base64,AAA", detail: "auto" } },
			{ type: "file", mime_type: "text/csv", base64: "QkJC", filename: "rows.csv" },
		]);
	});

	it("files alone are content blocks too, with defaults for missing metadata", () => {
		const content = promptMessageToContent({
			files: [{ type: "file", url: "rawbase64", mediaType: "", filename: "" }],
		});
		expect(content).toEqual([
			{ type: "file", mime_type: "application/octet-stream", base64: "rawbase64", filename: "file" },
		]);
	});
});

import { describe, expect, it, vi } from "vitest";

import { contentPreview, promptMessageToInput } from "./build-content";

const png = { type: "file" as const, url: "data:image/png;base64,AAA", mediaType: "image/png", filename: "a.png" };
const csv = { type: "file" as const, url: "data:text/csv;base64,QkJC", mediaType: "text/csv", filename: "rows.csv" };

describe("promptMessageToInput", () => {
	const upload = vi.fn((file: { filename?: string }) => Promise.resolve(`id-${file.filename}`));

	it("is null for nothing to send", async () => {
		expect(await promptMessageToInput(null, { vision: true, upload })).toBeNull();
		expect(await promptMessageToInput({ text: "   ", files: [] }, { vision: true, upload })).toBeNull();
	});

	it("keeps text-only as a plain string", async () => {
		expect(await promptMessageToInput({ text: "hi there", files: [] }, { vision: true, upload })).toEqual({
			content: "hi there",
			attachments: [],
		});
	});

	it("uploads every attachment and inlines only images, never file blocks", async () => {
		const input = await promptMessageToInput({ text: "look", files: [png, csv] }, { vision: true, upload });
		expect(input).toEqual({
			content: [
				{ type: "text", text: "look" },
				{ type: "image_url", image_url: { url: "data:image/png;base64,AAA", detail: "auto" } },
			],
			attachments: ["id-a.png", "id-rows.csv"],
		});
	});

	it("keeps images off a model without vision", async () => {
		const input = await promptMessageToInput({ text: "look", files: [png] }, { vision: false, upload });
		expect(input).toEqual({ content: "look", attachments: ["id-a.png"] });
	});

	it("an image survives a failed upload; any other file fails the send", async () => {
		const failing = vi.fn(() => Promise.reject(new Error("no store")));
		expect(await promptMessageToInput({ files: [png] }, { vision: true, upload: failing })).toEqual({
			content: [{ type: "image_url", image_url: { url: png.url, detail: "auto" } }],
			attachments: [],
		});
		await expect(promptMessageToInput({ files: [csv] }, { vision: true, upload: failing })).rejects.toThrow(
			"no store",
		);
		// Without vision the upload is the image's only way to the agent.
		await expect(promptMessageToInput({ files: [png] }, { vision: false, upload: failing })).rejects.toThrow(
			"no store",
		);
	});
});

describe("contentPreview", () => {
	it("shows the text, else the attachment count", () => {
		expect(contentPreview({ content: "hi", attachments: [] })).toBe("hi");
		expect(contentPreview({ content: [{ type: "text", text: "see" }], attachments: ["a"] })).toBe("see");
		expect(contentPreview({ content: [], attachments: ["a", "b"] })).toBe("2 attachments");
	});
});

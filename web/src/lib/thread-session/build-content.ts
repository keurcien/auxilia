import type { FileUIPart } from "@/components/ai-elements/attachments";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

/** A human turn as the backend accepts it: plain text, or LangChain content blocks. */
export type HumanContent = string | Array<Record<string, unknown>>;

/** A human turn ready to submit: its content, and the thread files it attaches. */
export type HumanInput = { content: HumanContent; attachments: string[] };

/** Stores one attachment as a thread file and resolves to its id. */
export type UploadFile = (file: FileUIPart) => Promise<string>;

/**
 * Turn a composer message into a human turn. Every attachment is uploaded as a
 * thread file (the run places it on the sandbox disk); images also go to the
 * model as `image_url` blocks when it has vision. Nothing else is inlined.
 * Text alone stays a string. Resolves to `null` when there is nothing to send.
 *
 * An image the model sees inline may fail to upload (no object store: the
 * agent takes images only); any other failure rejects, since the agent would
 * never see the file.
 */
export async function promptMessageToInput(
	message: PromptInputMessage | null | undefined,
	{ vision, upload }: { vision: boolean; upload: UploadFile },
): Promise<HumanInput | null> {
	if (!message) return null;
	const text = message.text?.trim() ? message.text : "";
	const files = message.files ?? [];
	if (!text && files.length === 0) return null;

	const parts: Array<Record<string, unknown>> = [];
	if (text) parts.push({ type: "text", text });
	const attachments: string[] = [];
	// One at a time: the backend numbers clashing names in arrival order.
	for (const file of files) {
		const isImage = file.mediaType.startsWith("image/");
		if (isImage && vision) {
			parts.push({ type: "image_url", image_url: { url: file.url, detail: "auto" } });
		}
		try {
			attachments.push(await upload(file));
		} catch (error) {
			// Only an image the model sees inline may go without its thread file.
			if (!(isImage && vision)) throw error;
		}
	}
	if (parts.length === 0 && attachments.length === 0) return null;
	const content =
		parts.length === 1 && parts[0].type === "text" ? (parts[0].text as string) : parts;
	return { content, attachments };
}

/** One line for a queued message: its text, else what it attaches. */
export function contentPreview({ content, attachments }: HumanInput): string {
	if (typeof content === "string" && content) return content;
	const text = Array.isArray(content)
		? content.find((p) => p.type === "text")?.text
		: undefined;
	if (typeof text === "string" && text.trim()) return text;
	const files = Math.max(attachments.length, Array.isArray(content) ? content.length : 0);
	return `${files} attachment${files === 1 ? "" : "s"}`;
}

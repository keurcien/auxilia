import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";

/** A human turn as the backend accepts it: plain text, or LangChain content blocks. */
export type HumanContent = string | Array<Record<string, unknown>>;

/**
 * Turn a composer message into the `content` of a human message. Text alone
 * stays a string; anything with attachments becomes content blocks — images
 * as `image_url`, other files as `file` blocks with their base64 payload.
 * Returns `null` when there is nothing to send.
 */
export function promptMessageToContent(
	message: PromptInputMessage | null | undefined,
): HumanContent | null {
	if (!message) return null;
	const text = "text" in message ? message.text?.trim() : undefined;
	const files = ("files" in message && message.files) || [];
	if (!text && files.length === 0) return null;

	const parts: Array<Record<string, unknown>> = [];
	if (text) parts.push({ type: "text", text: message.text });
	for (const file of files) {
		const mediaType = file.mediaType;
		if (mediaType.startsWith("image/")) {
			parts.push({
				type: "image_url",
				image_url: { url: file.url, detail: "auto" },
			});
		} else {
			const base64Match = file.url.match(/^data:[^;]*;base64,(.*)$/);
			parts.push({
				type: "file",
				mime_type: mediaType || "application/octet-stream",
				base64: base64Match ? base64Match[1] : file.url,
				filename: file.filename || "file",
			});
		}
	}
	return parts.length === 1 && parts[0].type === "text"
		? (parts[0].text as string)
		: parts;
}

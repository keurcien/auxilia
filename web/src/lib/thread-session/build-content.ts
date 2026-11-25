import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { UserFacingError } from "@/lib/api/errors";

/** A human turn as the backend accepts it: plain text, or LangChain content blocks. */
export type HumanContent = string | Array<Record<string, unknown>>;

export interface AttachmentReference {
	id: string;
	filename: string;
	mediaType: string;
}

export interface HumanInput {
	content: HumanContent;
	attachments: AttachmentReference[];
	displayText: string;
	inlineTextFiles: Array<{
		blockIndex: number;
		filename: string;
		mediaType: string;
	}>;
}

type UploadFile = (
	file: NonNullable<PromptInputMessage["files"]>[number],
) => Promise<AttachmentReference>;

const TEXT_EXTENSIONS = new Set([
	"bash",
	"c",
	"cc",
	"conf",
	"cpp",
	"css",
	"csv",
	"cts",
	"env",
	"go",
	"gql",
	"graphql",
	"h",
	"hpp",
	"htm",
	"html",
	"ini",
	"ipynb",
	"java",
	"js",
	"json",
	"jsonc",
	"jsonl",
	"jsonld",
	"jsx",
	"kt",
	"kts",
	"less",
	"lua",
	"markdown",
	"md",
	"mjs",
	"mts",
	"ndjson",
	"php",
	"properties",
	"py",
	"pyi",
	"r",
	"rb",
	"rs",
	"sass",
	"scss",
	"sh",
	"sql",
	"svelte",
	"swift",
	"toml",
	"ts",
	"tsx",
	"txt",
	"vue",
	"xml",
	"yaml",
	"yml",
	"zsh",
]);
const TEXT_APPLICATION_TYPES = new Set([
	"application/graphql",
	"application/json",
	"application/ld+json",
	"application/sql",
	"application/toml",
	"application/x-httpd-php",
	"application/x-ndjson",
	"application/x-sh",
	"application/xml",
	"application/yaml",
]);
const INLINE_TEXT_MAX_CHARS = 100_000;

function hasTextFileHint(
	file: NonNullable<PromptInputMessage["files"]>[number],
): boolean {
	const extension = file.filename?.split(".").pop()?.toLowerCase() ?? "";
	return (
		file.mediaType.startsWith("text/") ||
		TEXT_APPLICATION_TYPES.has(file.mediaType) ||
		TEXT_EXTENSIONS.has(extension) ||
		["dockerfile", "makefile"].includes(file.filename?.toLowerCase() ?? "")
	);
}

async function textAttachmentContent(
	file: NonNullable<PromptInputMessage["files"]>[number],
): Promise<string | null> {
	const bytes = new Uint8Array(
		await (await fetch(file.url)).arrayBuffer(),
	);
	let text: string;
	let legacyDecoded = false;
	try {
		const sample = bytes.subarray(0, 256);
		const pairs = Math.floor(sample.length / 2);
		let evenZeroes = 0;
		let oddZeroes = 0;
		for (let index = 0; index < pairs * 2; index += 2) {
			if (sample[index] === 0) evenZeroes += 1;
			if (sample[index + 1] === 0) oddZeroes += 1;
		}
		if (
			bytes.length >= 2 &&
			((bytes[0] === 0xff && bytes[1] === 0xfe) ||
				(bytes[0] === 0xfe && bytes[1] === 0xff))
		) {
			text = new TextDecoder(
				bytes[0] === 0xff ? "utf-16le" : "utf-16be",
				{ fatal: true },
			).decode(bytes.subarray(2));
		} else if (
			pairs >= 1 &&
			oddZeroes > pairs / 2 &&
			evenZeroes < pairs / 10
		) {
			text = new TextDecoder("utf-16le", { fatal: true }).decode(bytes);
		} else if (
			pairs >= 1 &&
			evenZeroes > pairs / 2 &&
			oddZeroes < pairs / 10
		) {
			text = new TextDecoder("utf-16be", { fatal: true }).decode(bytes);
		} else {
			text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		}
	} catch {
		if (!hasTextFileHint(file)) return null;
		try {
			text = new TextDecoder("windows-1252", { fatal: true }).decode(bytes);
			legacyDecoded = true;
		} catch {
			return null;
		}
	}
	const characters = [...text];
	if (
		legacyDecoded &&
		characters.length > 0 &&
		characters.filter((char) => char.charCodeAt(0) >= 128).length /
			characters.length >
			0.3
	) {
		return null;
	}
	return characters.some(
		(char) =>
			(char.charCodeAt(0) < 32 && !"\t\n\r\f\u001b".includes(char)) ||
			(char.charCodeAt(0) >= 127 && char.charCodeAt(0) <= 159),
	)
		? null
		: text;
}

function inlineTextBlock(filename: string, text: string) {
	return {
		type: "text",
		text: `Attached text file "${filename}":\n\n${text}`,
	};
}

/**
 * Prepare a human turn. Text files are decoded into marked text blocks and
 * never require storage. Other files are stored when storage is available;
 * vision-capable models also receive images inline.
 */
export async function promptMessageToInput(
	message: PromptInputMessage | null | undefined,
	options: { vision: boolean; upload?: UploadFile },
): Promise<HumanInput | null> {
	if (!message) return null;
	const text = message.text?.trim() ? message.text : "";
	const files = message.files ?? [];
	if (!text && files.length === 0) return null;
	if (files.length > 10) {
		throw new UserFacingError("A message can contain at most 10 files.");
	}

	const parts: Array<Record<string, unknown>> = [];
	if (text) parts.push({ type: "text", text });
	const attachments: AttachmentReference[] = [];
	const inlineTextFiles: HumanInput["inlineTextFiles"] = [];
	const prepared = await Promise.all(
		files.map(async (file) => ({
			file,
			textContent: await textAttachmentContent(file),
		})),
	);
	let inlineTextChars = 0;
	for (const { file, textContent } of prepared) {
		const image = file.mediaType.startsWith("image/") && textContent == null;
		if (image && options.vision) {
			parts.push({
				type: "image_url",
				image_url: { url: file.url, detail: "auto" },
			});
		}
		const fitsInline =
			textContent != null &&
			inlineTextChars + textContent.length <= INLINE_TEXT_MAX_CHARS;
		if (textContent != null && !fitsInline && options.upload == null) {
			throw new UserFacingError(
				`"${file.filename || "file"}" is too large to send as text: attached text files can contain at most ${INLINE_TEXT_MAX_CHARS.toLocaleString("en-US")} characters per message. Larger files need an agent with a sandbox.`,
			);
		}
		if (textContent != null && fitsInline) {
			inlineTextChars += textContent.length;
			const filename = file.filename || "file.txt";
			const mediaType =
				file.mediaType.startsWith("text/") ||
				TEXT_APPLICATION_TYPES.has(file.mediaType)
					? file.mediaType
					: "text/plain";
			inlineTextFiles.push({
				blockIndex: parts.length,
				filename,
				mediaType,
			});
			parts.push(inlineTextBlock(filename, textContent));
			continue;
		}
		if (options.upload != null) {
			try {
				const uploaded = await options.upload(file);
				attachments.push(uploaded);
				continue;
			} catch (error) {
				if (image && options.vision) continue;
				throw error;
			}
		}
		if (image && options.vision) continue;
		throw new UserFacingError(
			`"${file.filename || "file"}" cannot be attached: this agent has no sandbox, so only images and text files can be sent.`,
		);
	}
	if (parts.length === 0 && attachments.length === 0) return null;
	const content =
		parts.length === 1 &&
		parts[0].type === "text" &&
		inlineTextFiles.length === 0
			? (parts[0].text as string)
			: parts;
	return { content, attachments, displayText: text, inlineTextFiles };
}

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

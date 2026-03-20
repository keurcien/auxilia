import type { JSONRPCRequest } from "@modelcontextprotocol/sdk/types.js";

export const DOWNLOAD_FILE_METHOD = "ui/download-file";

const FILE_URI_PROTOCOL = "file:";
const SVG_MIME_TYPE = "image/svg+xml";
const PNG_MIME_TYPE = "image/png";
const BASE64_PATTERN =
	/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

const MAX_FILENAME_LENGTH = 128;
const MAX_SVG_BYTES = 2 * 1024 * 1024;
const MAX_PNG_BYTES = 20 * 1024 * 1024;
const MAX_PNG_BASE64_LENGTH = Math.ceil((MAX_PNG_BYTES * 4) / 3) + 4;

type DownloadMimeType = typeof SVG_MIME_TYPE | typeof PNG_MIME_TYPE;

type DownloadResource = {
	uri: string;
	mimeType: string;
	text?: unknown;
	blob?: unknown;
};

export type DownloadFilePayload = {
	fileName: string;
	mimeType: DownloadMimeType;
	body: string | ArrayBuffer;
};

export type DownloadFileParseResult =
	| {
			ok: true;
			payload: DownloadFilePayload;
	  }
	| {
			ok: false;
			reason: string;
	  };

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === "object" && value !== null;

const decodeBase64 = (value: string): ArrayBuffer | null => {
	if (typeof globalThis.atob !== "function") {
		return null;
	}

	try {
		const binary = globalThis.atob(value);
		const bytes = new Uint8Array(binary.length);
		for (let i = 0; i < binary.length; i += 1) {
			bytes[i] = binary.charCodeAt(i);
		}
		return bytes.buffer;
	} catch {
		return null;
	}
};

const sanitizeFileName = (
	candidate: string,
	mimeType: DownloadMimeType,
): string | null => {
	const normalized = candidate
		.trim()
		.toLowerCase()
		.replace(/[^a-z0-9._-]+/g, "-")
		.replace(/-+/g, "-")
		.replace(/^-+|-+$/g, "")
		.replace(/^\.+/, "")
		.replace(/\.+$/g, "");

	if (!normalized || normalized === "." || normalized === "..") {
		return null;
	}

	const extension = mimeType === SVG_MIME_TYPE ? "svg" : "png";
	const baseName = normalized
		.replace(/\.(svg|png)$/i, "")
		.replace(/\.+$/g, "")
		.slice(0, MAX_FILENAME_LENGTH - extension.length - 1);

	if (!baseName) {
		return null;
	}

	return `${baseName}.${extension}`;
};

const getSafeFileNameFromUri = (
	uri: string,
	mimeType: DownloadMimeType,
): string | null => {
	let parsedUri: URL;
	try {
		parsedUri = new URL(uri);
	} catch {
		return null;
	}

	if (
		parsedUri.protocol !== FILE_URI_PROTOCOL ||
		parsedUri.search.length > 0 ||
		parsedUri.hash.length > 0
	) {
		return null;
	}

	const segments = parsedUri.pathname.split("/").filter((segment) => segment);
	if (segments.length !== 1) {
		return null;
	}

	let decodedSegment: string;
	try {
		decodedSegment = decodeURIComponent(segments[0]);
	} catch {
		return null;
	}

	return sanitizeFileName(decodedSegment, mimeType);
};

const getSingleEmbeddedResource = (
	params: unknown,
): DownloadResource | null => {
	if (!isRecord(params)) {
		return null;
	}

	const rawContents = params.contents;
	if (!Array.isArray(rawContents) || rawContents.length !== 1) {
		return null;
	}

	const [rawContent] = rawContents;
	if (!isRecord(rawContent) || rawContent.type !== "resource") {
		return null;
	}

	const rawResource = rawContent.resource;
	if (!isRecord(rawResource)) {
		return null;
	}

	const uri = rawResource.uri;
	const mimeType = rawResource.mimeType;
	if (typeof uri !== "string" || typeof mimeType !== "string") {
		return null;
	}

	return {
		uri,
		mimeType,
		text: rawResource.text,
		blob: rawResource.blob,
	};
};

const parseSvgDownload = (
	resource: DownloadResource,
	fileName: string,
): DownloadFileParseResult => {
	if (resource.mimeType !== SVG_MIME_TYPE) {
		return {
			ok: false,
			reason: "unsupported_mime_type",
		};
	}

	if (typeof resource.text !== "string" || resource.text.trim().length === 0) {
		return {
			ok: false,
			reason: "invalid_svg_payload",
		};
	}

	if (resource.blob !== undefined && resource.blob !== null) {
		return {
			ok: false,
			reason: "invalid_svg_payload",
		};
	}

	const byteLength = new TextEncoder().encode(resource.text).byteLength;
	if (byteLength > MAX_SVG_BYTES) {
		return {
			ok: false,
			reason: "payload_too_large",
		};
	}

	return {
		ok: true,
		payload: {
			fileName,
			mimeType: SVG_MIME_TYPE,
			body: resource.text,
		},
	};
};

const parsePngDownload = (
	resource: DownloadResource,
	fileName: string,
): DownloadFileParseResult => {
	if (resource.mimeType !== PNG_MIME_TYPE) {
		return {
			ok: false,
			reason: "unsupported_mime_type",
		};
	}

	if (resource.text !== undefined && resource.text !== null) {
		return {
			ok: false,
			reason: "invalid_png_payload",
		};
	}

	if (typeof resource.blob !== "string") {
		return {
			ok: false,
			reason: "invalid_png_payload",
		};
	}

	const normalizedBase64 = resource.blob.replace(/\s+/g, "");
	if (
		normalizedBase64.length === 0 ||
		normalizedBase64.length > MAX_PNG_BASE64_LENGTH ||
		!BASE64_PATTERN.test(normalizedBase64)
	) {
		return {
			ok: false,
			reason: "invalid_png_payload",
		};
	}

	const bytes = decodeBase64(normalizedBase64);
	if (!bytes || bytes.byteLength === 0 || bytes.byteLength > MAX_PNG_BYTES) {
		return {
			ok: false,
			reason: "payload_too_large",
		};
	}

	return {
		ok: true,
		payload: {
			fileName,
			mimeType: PNG_MIME_TYPE,
			body: bytes,
		},
	};
};

export const parseDownloadFileRequest = (
	request: JSONRPCRequest,
): DownloadFileParseResult => {
	if (request.method !== DOWNLOAD_FILE_METHOD) {
		return {
			ok: false,
			reason: "unsupported_method",
		};
	}

	const resource = getSingleEmbeddedResource(request.params);
	if (!resource) {
		return {
			ok: false,
			reason: "invalid_request_shape",
		};
	}

	if (resource.mimeType !== SVG_MIME_TYPE && resource.mimeType !== PNG_MIME_TYPE) {
		return {
			ok: false,
			reason: "unsupported_mime_type",
		};
	}

	const fileName = getSafeFileNameFromUri(resource.uri, resource.mimeType);
	if (!fileName) {
		return {
			ok: false,
			reason: "unsafe_file_uri",
		};
	}

	return resource.mimeType === SVG_MIME_TYPE
		? parseSvgDownload(resource, fileName)
		: parsePngDownload(resource, fileName);
};

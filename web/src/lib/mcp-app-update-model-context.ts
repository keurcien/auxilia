import type { JSONRPCRequest } from "@modelcontextprotocol/sdk/types.js";

export const UPDATE_MODEL_CONTEXT_METHOD = "ui/update-model-context";

const SVG_MIME_TYPE = "image/svg+xml";
const PNG_MIME_TYPE = "image/png";

type ExportFormat = "svg" | "png";
type ExportMimeType = typeof SVG_MIME_TYPE | typeof PNG_MIME_TYPE;

export type NormalizedExportMetadata = {
	format: ExportFormat;
	fileName: string;
	mimeType: ExportMimeType;
	width: number;
	height: number;
	byteLength?: number;
	timestamp: string;
};

type UpdateModelContextPayload = {
	content?: unknown[];
	structuredContent?: Record<string, unknown>;
	exportMetadata: NormalizedExportMetadata | null;
};

export type UpdateModelContextParseResult =
	| {
			ok: true;
			payload: UpdateModelContextPayload;
	  }
	| {
			ok: false;
			reason: string;
	  };

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === "object" && value !== null;

const isFinitePositiveNumber = (value: unknown): value is number =>
	typeof value === "number" && Number.isFinite(value) && value > 0;

const normalizeExportFormat = (value: unknown): ExportFormat | null => {
	if (typeof value !== "string") {
		return null;
	}

	const normalized = value.trim().toLowerCase();
	if (normalized === "svg" || normalized === "png") {
		return normalized;
	}

	return null;
};

const normalizeExportMimeType = (value: unknown): ExportMimeType | null => {
	if (value === SVG_MIME_TYPE || value === PNG_MIME_TYPE) {
		return value;
	}
	return null;
};

const normalizeExportTimestamp = (value: unknown): string | null => {
	if (typeof value !== "string" || value.trim().length === 0) {
		return null;
	}

	const date = new Date(value);
	if (Number.isNaN(date.getTime())) {
		return null;
	}

	return date.toISOString();
};

const normalizeExportFileName = (value: unknown): string | null => {
	if (typeof value !== "string") {
		return null;
	}

	const trimmed = value.trim();
	if (trimmed.length === 0 || trimmed.length > 256) {
		return null;
	}

	return trimmed;
};

const parseNormalizedExportMetadata = (
	structuredContent: Record<string, unknown> | undefined,
): UpdateModelContextParseResult => {
	if (!structuredContent) {
		return {
			ok: true,
			payload: {
				exportMetadata: null,
			},
		};
	}

	const rawExport = structuredContent.export;
	if (rawExport === undefined) {
		return {
			ok: true,
			payload: {
				exportMetadata: null,
			},
		};
	}

	if (!isRecord(rawExport)) {
		return {
			ok: false,
			reason: "invalid_export_metadata",
		};
	}

	const format = normalizeExportFormat(rawExport.format);
	const fileName = normalizeExportFileName(rawExport.fileName);
	const mimeType = normalizeExportMimeType(rawExport.mimeType);
	const timestamp = normalizeExportTimestamp(rawExport.exportedAt);
	const width = rawExport.width;
	const height = rawExport.height;
	const byteLength = rawExport.byteLength;

	if (
		!format ||
		!fileName ||
		!mimeType ||
		!timestamp ||
		!isFinitePositiveNumber(width) ||
		!isFinitePositiveNumber(height)
	) {
		return {
			ok: false,
			reason: "invalid_export_metadata",
		};
	}

	const expectedMimeType = format === "svg" ? SVG_MIME_TYPE : PNG_MIME_TYPE;
	if (mimeType !== expectedMimeType) {
		return {
			ok: false,
			reason: "invalid_export_metadata",
		};
	}

	if (
		byteLength !== undefined &&
		(!isFinitePositiveNumber(byteLength) || !Number.isInteger(byteLength))
	) {
		return {
			ok: false,
			reason: "invalid_export_metadata",
		};
	}

	return {
		ok: true,
		payload: {
			exportMetadata: {
				format,
				fileName,
				mimeType,
				width,
				height,
				byteLength:
					typeof byteLength === "number" ? Math.trunc(byteLength) : undefined,
				timestamp,
			},
		},
	};
};

export const parseUpdateModelContextRequest = (
	request: JSONRPCRequest,
): UpdateModelContextParseResult => {
	if (request.method !== UPDATE_MODEL_CONTEXT_METHOD) {
		return {
			ok: false,
			reason: "unsupported_method",
		};
	}

	if (!isRecord(request.params)) {
		return {
			ok: false,
			reason: "invalid_request_shape",
		};
	}

	const rawContent = request.params.content;
	const rawStructuredContent = request.params.structuredContent;

	if (rawContent !== undefined && !Array.isArray(rawContent)) {
		return {
			ok: false,
			reason: "invalid_request_shape",
		};
	}

	if (
		rawStructuredContent !== undefined &&
		!isRecord(rawStructuredContent)
	) {
		return {
			ok: false,
			reason: "invalid_request_shape",
		};
	}

	if (rawContent === undefined && rawStructuredContent === undefined) {
		return {
			ok: false,
			reason: "empty_context_update",
		};
	}

	const parsedExportMetadata = parseNormalizedExportMetadata(
		rawStructuredContent as Record<string, unknown> | undefined,
	);
	if (!parsedExportMetadata.ok) {
		return parsedExportMetadata;
	}

	return {
		ok: true,
		payload: {
			content: rawContent,
			structuredContent: rawStructuredContent as
				| Record<string, unknown>
				| undefined,
			exportMetadata: parsedExportMetadata.payload.exportMetadata,
		},
	};
};

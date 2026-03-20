"use client";

import { useMemo } from "react";
import { AppRenderer } from "@mcp-ui/client";
import type { ToolUIPart } from "ai";
import { api } from "@/lib/api/client";
import {
	DOWNLOAD_FILE_METHOD,
	parseDownloadFileRequest,
} from "@/lib/mcp-app-download-file";
import {
	parseUpdateModelContextRequest,
	UPDATE_MODEL_CONTEXT_METHOD,
} from "@/lib/mcp-app-update-model-context";
import {
	useMcpAppExportMetadata,
	useMcpAppExportMetadataStore,
} from "@/stores/mcp-app-export-metadata-store";
import { cn } from "@/lib/utils";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

export type McpAppToolInfo = {
	resourceUri: string;
	serverId: string;
};

type McpAppWidgetProps = {
	toolPart: ToolUIPart;
	toolName: string;
	appToolInfo: McpAppToolInfo;
	threadId: string;
	messageId: string;
	toolCallId: string;
	className?: string;
};

const AUXILIA_METADATA_KEY = "auxilia";
const MCP_APP_RESOURCE_URI_KEY = "mcpAppResourceUri";
const MCP_SERVER_ID_KEY = "mcpServerId";

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === "object" && value !== null;

export const getMcpAppToolInfo = (
	toolPart: ToolUIPart,
): McpAppToolInfo | null => {
	const providerMetadata = toolPart.callProviderMetadata;
	if (!isRecord(providerMetadata)) {
		return null;
	}

	const auxiliaMetadata = providerMetadata[AUXILIA_METADATA_KEY];
	if (!isRecord(auxiliaMetadata)) {
		return null;
	}

	const resourceUri = auxiliaMetadata[MCP_APP_RESOURCE_URI_KEY];
	const serverId = auxiliaMetadata[MCP_SERVER_ID_KEY];

	if (
		typeof resourceUri !== "string" ||
		typeof serverId !== "string" ||
		resourceUri.trim().length === 0 ||
		serverId.trim().length === 0
	) {
		return null;
	}

	return {
		resourceUri,
		serverId,
	};
};

const toToolInput = (input: unknown): Record<string, unknown> | undefined => {
	if (input === undefined || input === null) {
		return undefined;
	}

	if (typeof input === "object" && !Array.isArray(input)) {
		return input as Record<string, unknown>;
	}

	return { value: input };
};

const stringifyToolOutput = (value: unknown): string => {
	if (value === undefined || value === null) {
		return "";
	}

	if (typeof value === "string") {
		return value;
	}

	try {
		return JSON.stringify(value, null, 2);
	} catch {
		return String(value);
	}
};

const hasStructuredContent = (
	output: unknown,
): output is { _text: unknown; structuredContent: Record<string, unknown> } =>
	isRecord(output) &&
	"structuredContent" in output &&
	isRecord(output.structuredContent);

export const getToolOutputText = (output: unknown): unknown => {
	if (hasStructuredContent(output)) {
		return output._text;
	}
	return output;
};

const toCallToolResult = (toolPart: ToolUIPart): CallToolResult | undefined => {
	if (toolPart.output === undefined && !toolPart.errorText) {
		return undefined;
	}

	const isError = Boolean(toolPart.errorText);
	const rawOutput = toolPart.output;
	const textOutput = getToolOutputText(rawOutput);
	const text = toolPart.errorText ?? stringifyToolOutput(textOutput);

	const result: CallToolResult = {
		content: text ? [{ type: "text", text }] : [],
		isError,
	};

	if (hasStructuredContent(rawOutput)) {
		result.structuredContent = rawOutput.structuredContent;
	}

	return result;
};

export const McpAppWidget = ({
	toolPart,
	toolName,
	appToolInfo,
	threadId,
	messageId,
	toolCallId,
	className,
}: McpAppWidgetProps) => {
	const sandboxConfig = useMemo(
		() => ({ url: new URL("/sandbox.html", window.location.origin) }),
		[],
	);
	const setExportMetadata = useMcpAppExportMetadataStore(
		(state) => state.setExportMetadata,
	);
	const exportMetadata = useMcpAppExportMetadata(
		threadId,
		messageId,
		toolCallId,
	);

	if (typeof window === "undefined") {
		return null;
	}

	return (
		<div
			className={cn(
				"mt-2 w-full min-w-0 overflow-hidden [&_iframe]:w-full! [&_iframe]:max-w-full!",
				className,
			)}
		>
			<AppRenderer
				toolName={toolName}
				toolResourceUri={appToolInfo.resourceUri}
				sandbox={sandboxConfig}
				toolInput={toToolInput(toolPart.input)}
				toolResult={toCallToolResult(toolPart)}
				onReadResource={async ({ uri }) => {
					const response = await api.post(
						`/mcp-servers/${appToolInfo.serverId}/app/read-resource`,
						{ uri },
					);
					return response.data;
				}}
				onCallTool={async ({ name, arguments: args }) => {
					const response = await api.post(
						`/mcp-servers/${appToolInfo.serverId}/app/call-tool`,
						{
							toolName: name,
							arguments: args ?? null,
						},
					);

					const data = response.data;

					if (data.content) {
						data.content = data.content.map(
							(block: Record<string, unknown>) => {
								const cleaned = { ...block };
								if (cleaned.annotations === null) delete cleaned.annotations;
								if (cleaned.Meta === null) delete cleaned.Meta;
								if (cleaned._meta === null) delete cleaned._meta;
								return cleaned;
							},
						);
					}
					if (data._meta === null) delete data._meta;
					if (data.Meta === null) delete data.Meta;

					return data;
				}}
				onFallbackRequest={async (request) => {
					if (request.method === DOWNLOAD_FILE_METHOD) {
						const parsedRequest = parseDownloadFileRequest(request);
						if (!parsedRequest.ok) {
							return { isError: true };
						}

						try {
							const blob = new Blob([parsedRequest.payload.body], {
								type: parsedRequest.payload.mimeType,
							});
							const downloadUrl = URL.createObjectURL(blob);

							try {
								const anchor = document.createElement("a");
								anchor.href = downloadUrl;
								anchor.download = parsedRequest.payload.fileName;
								anchor.rel = "noopener noreferrer";
								anchor.style.display = "none";
								document.body.appendChild(anchor);
								anchor.click();
								anchor.remove();
							} finally {
								URL.revokeObjectURL(downloadUrl);
							}

							return { isError: false };
						} catch {
							return { isError: true };
						}
					}

					if (request.method === UPDATE_MODEL_CONTEXT_METHOD) {
						const parsedRequest = parseUpdateModelContextRequest(request);
						if (!parsedRequest.ok) {
							return { isError: true };
						}

						if (parsedRequest.payload.exportMetadata) {
							setExportMetadata({
								threadId,
								messageId,
								toolCallId,
								metadata: parsedRequest.payload.exportMetadata,
							});
						}

						return {};
					}

					return { isError: true };
				}}
			/>
			{exportMetadata && (
				<details className="mt-2 rounded-md border border-dashed border-muted-foreground/40 bg-muted/20 px-3 py-2 text-xs">
					<summary className="cursor-pointer font-medium text-muted-foreground">
						Export metadata (debug)
					</summary>
					<pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-muted-foreground">
						{JSON.stringify(exportMetadata, null, 2)}
					</pre>
				</details>
			)}
		</div>
	);
};

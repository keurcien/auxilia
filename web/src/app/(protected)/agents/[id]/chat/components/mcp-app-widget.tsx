"use client";

import { AppRenderer } from "@mcp-ui/client";
import type { ToolUIPart } from "ai";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { useMcpHostContext } from "@/hooks/use-mcp-host-context";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

export type McpAppToolInfo = {
	resourceUri: string;
	serverId: string;
};

type McpAppWidgetProps = {
	toolPart: ToolUIPart;
	toolName: string;
	appToolInfo: McpAppToolInfo;
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

const toCallToolResult = (toolPart: ToolUIPart): CallToolResult | undefined => {
	console.log(toolPart);
	if (toolPart.output === undefined && !toolPart.errorText) {
		return undefined;
	}

	const isError = Boolean(toolPart.errorText);
	const text = toolPart.errorText ?? stringifyToolOutput(toolPart.output);

	return {
		content: text ? [{ type: "text", text }] : [],
		isError,
	};
};

export const McpAppWidget = ({
	toolPart,
	toolName,
	appToolInfo,
	className,
}: McpAppWidgetProps) => {
	const hostContext = useMcpHostContext();

	if (typeof window === "undefined") {
		return null;
	}

	return (
		<div
			className={cn(
				"mt-2 w-full min-w-0 overflow-hidden [&_iframe]:w-full [&_iframe]:max-w-full",
				className,
			)}
		>
			<AppRenderer
				toolName={toolName}
				toolResourceUri={appToolInfo.resourceUri}
				sandbox={{ url: new URL("/sandbox.html", window.location.origin) }}
				toolInput={toToolInput(toolPart.input)}
				toolResult={toCallToolResult(toolPart)}
				hostContext={hostContext}
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
			/>
		</div>
	);
};

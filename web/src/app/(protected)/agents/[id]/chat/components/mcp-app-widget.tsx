"use client";

import { AppRenderer } from "@mcp-ui/client";
import type { ToolUIPart } from "ai";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import type { McpAppToolInfo } from "@/hooks/use-mcp-app-tools";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";

type McpAppWidgetProps = {
	toolPart: ToolUIPart;
	toolName: string;
	appToolInfo: McpAppToolInfo;
	className?: string;
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
	if (typeof window === "undefined") {
		return null;
	}

	return (
		<div className={cn("mt-2 w-full min-w-0 overflow-hidden [&_iframe]:max-w-full", className)}>
			<AppRenderer
				toolName={toolName}
				toolResourceUri={appToolInfo.resourceUri}
				sandbox={{ url: new URL("/sandbox.html", window.location.origin) }}
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
					return response.data;
				}}
			/>
		</div>
	);
};

"use client";

import { useCallback, useMemo } from "react";
import { AppRenderer } from "@mcp-ui/client";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import type { CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import { useMcpHostContext } from "@/hooks/use-mcp-host-context";

export type McpAppToolInfo = {
	resourceUri: string;
	serverId: string;
};

type McpAppWidgetProps = {
	input?: Record<string, unknown>;
	output?: unknown;
	structuredContent?: Record<string, unknown>;
	errorText?: string;
	toolName: string;
	appToolInfo: McpAppToolInfo;
	className?: string;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
	typeof value === "object" && value !== null;

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
): output is { structuredContent: Record<string, unknown> } =>
	isRecord(output) &&
	"structuredContent" in output &&
	isRecord(output.structuredContent);

// Content hash used to keep useMemo stable across parent re-renders that
// rebuild the same value into a fresh reference.
const stableKey = (value: unknown): string => {
	if (value === null || value === undefined) return "";
	if (typeof value === "string") return value;
	try {
		return JSON.stringify(value);
	} catch {
		return String(value);
	}
};

const toCallToolResult = (
	output: unknown,
	errorText: string | undefined,
	structuredContent?: Record<string, unknown>,
): CallToolResult | undefined => {
	if (output === undefined && !errorText && !structuredContent) {
		return undefined;
	}

	const isError = Boolean(errorText);
	const text = errorText ?? stringifyToolOutput(output);

	const result: CallToolResult = {
		content: text ? [{ type: "text", text }] : [],
		isError,
	};

	if (structuredContent) {
		result.structuredContent = structuredContent;
	} else if (hasStructuredContent(output)) {
		result.structuredContent = output.structuredContent;
	}

	return result;
};

export const McpAppWidget = ({
	input,
	output,
	structuredContent,
	errorText,
	toolName,
	appToolInfo,
	className,
}: McpAppWidgetProps) => {
	const hostContext = useMcpHostContext();
	const sandboxConfig = useMemo(
		() => ({ url: new URL("/sandbox.html", window.location.origin) }),
		[],
	);

	const serverId = appToolInfo.serverId;

	// Parents typically rebuild `input` / `output` / `structuredContent` on every
	// render (e.g. page.tsx runs JSON.parse on each pass via getToolOutputContent),
	// so ref-based memo keys invalidate every tick. Use string keys derived from
	// the content so the memoized objects stay stable across no-op re-renders —
	// otherwise AppRenderer re-syncs the sandboxed iframe on every tick and
	// floods the console with "Ignoring message from unknown source" and the
	// widget keeps re-measuring.
	const inputKey = input ? stableKey(input) : "";
	const outputKey = output === undefined ? "" : stableKey(output);
	const structuredKey = structuredContent ? stableKey(structuredContent) : "";

	const toolInput = useMemo(
		() => input,
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[inputKey],
	);

	const toolResult = useMemo(
		() => toCallToolResult(output, errorText, structuredContent),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[outputKey, errorText, structuredKey],
	);

	const onReadResource = useCallback(
		async ({ uri }: { uri: string }) => {
			const response = await api.post(
				`/mcp-servers/${serverId}/app/read-resource`,
				{ uri },
			);
			return response.data;
		},
		[serverId],
	);

	const onCallTool = useCallback(
		async ({
			name,
			arguments: args,
		}: {
			name: string;
			arguments?: Record<string, unknown> | null;
		}) => {
			const response = await api.post(
				`/mcp-servers/${serverId}/app/call-tool`,
				{ toolName: name, arguments: args ?? null },
			);

			const data = response.data;

			if (data.content) {
				data.content = data.content.map((block: Record<string, unknown>) => {
					const cleaned = { ...block };
					if (cleaned.annotations === null) delete cleaned.annotations;
					if (cleaned.Meta === null) delete cleaned.Meta;
					if (cleaned._meta === null) delete cleaned._meta;
					return cleaned;
				});
			}
			if (data._meta === null) delete data._meta;
			if (data.Meta === null) delete data.Meta;

			return data;
		},
		[serverId],
	);

	if (typeof window === "undefined") {
		return null;
	}

	return (
		<div
			className={cn(
				"mt-2 w-full min-w-0 overflow-hidden",
				// AppRenderer has no autoResize option and writes iframe.style.height
				// directly in response to `onsizechange`. When the app's body uses
				// `height: 100%`, that resize reflows content, which re-measures and
				// posts again — an unbounded growth loop. Cap the iframe height with
				// !important so the library's inline style can't actually grow the
				// element; the handshake settles after one frame.
				"[&_iframe]:w-full! [&_iframe]:max-w-full! [&_iframe]:max-h-[70vh]!",
				className,
			)}
		>
			<AppRenderer
				toolName={toolName}
				toolResourceUri={appToolInfo.resourceUri}
				sandbox={sandboxConfig}
				hostContext={hostContext}
				toolInput={toolInput}
				toolResult={toolResult}
				onReadResource={onReadResource}
				onCallTool={onCallTool}
			/>
		</div>
	);
};

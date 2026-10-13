"use client";

import { useCallback, useMemo } from "react";
import { AppRenderer } from "@mcp-ui/client";
import * as mcpAppsApi from "@/lib/api/resources/mcp-apps";
import { cn } from "@/lib/utils";
import {
	ErrorCode,
	McpError,
	type CallToolResult,
	type JSONRPCRequest,
} from "@modelcontextprotocol/sdk/types.js";
import type { McpUiDisplayMode } from "@modelcontextprotocol/ext-apps";
import { useMcpHostContext } from "@/hooks/use-mcp-host-context";
import type { McpAppToolInfo } from "@/lib/transcript";

export type { McpAppToolInfo };

/** MCP Apps display modes auxilia presents: `fullscreen` is the side panel. */
export type AppDisplayMode = Extract<McpUiDisplayMode, "inline" | "fullscreen">;
const AVAILABLE_DISPLAY_MODES: McpUiDisplayMode[] = ["inline", "fullscreen"];

/** One MCP app tool call, enough to render it anywhere (inline or the panel). */
export type DisplayedApp = Pick<
	McpAppWidgetProps,
	"input" | "output" | "structuredContent" | "errorText" | "toolName" | "appToolInfo"
>;

type McpAppWidgetProps = {
	input?: Record<string, unknown>;
	output?: unknown;
	structuredContent?: Record<string, unknown>;
	errorText?: string;
	toolName: string;
	appToolInfo: McpAppToolInfo;
	className?: string;
	/** Told to the app through `hostContext.displayMode`; `fullscreen` fills its container. */
	displayMode?: AppDisplayMode;
	/** Answers the app's `ui/request-display-mode`, returning the mode now in effect. */
	onRequestDisplayMode?: (mode: McpUiDisplayMode) => McpUiDisplayMode;
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

// When the result already carries a server-rendered view, forwarding
// `toolInput` causes renderers like Prefab's to re-execute the LLM's `code`
// argument client-side and overwrite the server view.
const resultHasView = (result: CallToolResult | undefined): boolean =>
	isRecord(result?.structuredContent) && "view" in result.structuredContent;

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

// Stable (module-level) references so AppRenderer doesn't re-sync the iframe on
// every render. Advertise the capabilities the host actually proxies: tool calls
// (onCallTool), resource reads (onReadResource) and link opening (onOpenLink).
const HOST_INFO = { name: "auxilia", version: "1.0.0" };
const HOST_CAPABILITIES = {
	serverTools: {},
	serverResources: {},
	openLinks: {},
};

export const McpAppWidget = ({
	input,
	output,
	structuredContent,
	errorText,
	toolName,
	appToolInfo,
	className,
	displayMode = "inline",
	onRequestDisplayMode,
}: McpAppWidgetProps) => {
	const baseHostContext = useMcpHostContext();
	const hostContext = useMemo(
		() => ({
			...baseHostContext,
			displayMode,
			availableDisplayModes: AVAILABLE_DISPLAY_MODES,
		}),
		[baseHostContext, displayMode],
	);
	const sandboxConfig = useMemo(
		() => ({ url: new URL("/sandbox.html", window.location.origin) }),
		[],
	);

	const serverId = appToolInfo.serverId;

	// toCallToolResult(...) allocates a fresh wrapper, and page.tsx rebuilds
	// `output` / `structuredContent` on every render (JSON.parse runs per pass
	// in getToolOutputContent). AppRenderer tracks toolResult by reference
	// identity, so without this memo it would re-sync the sandboxed iframe on
	// every tick — flooding the console with "Ignoring message from unknown
	// source" and keeping the widget re-measuring. Key by a content hash so
	// upstream ref-churn can't invalidate us.
	const outputKey = output === undefined ? "" : stableKey(output);
	const structuredKey = structuredContent ? stableKey(structuredContent) : "";

	const toolResult = useMemo(
		() => toCallToolResult(output, errorText, structuredContent),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[outputKey, errorText, structuredKey],
	);

	// Memoize like toolResult: AppRenderer tracks toolInput by reference identity,
	// so re-sending a fresh-but-equal object after the result arrives makes apps
	// (e.g. Metabase) reset to their "edited query — press Run" draft state. Key by
	// a content hash so parent re-renders can't churn the reference.
	const hasView = resultHasView(toolResult);
	const inputKey = input === undefined ? "" : stableKey(input);
	const effectiveToolInput = useMemo(
		() => (hasView ? undefined : input),
		// eslint-disable-next-line react-hooks/exhaustive-deps
		[inputKey, hasView],
	);

	const onReadResource = useCallback(
		async ({ uri }: { uri: string }) => {
			return mcpAppsApi.readMcpAppResource(serverId, uri);
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
			const data = (await mcpAppsApi.callMcpAppTool(
				serverId,
				name,
				args ?? null,
			)) as CallToolResult & Record<string, unknown>;

			if (data.content) {
				data.content = data.content.map((block) => {
					const cleaned: Record<string, unknown> = { ...block };
					if (cleaned.annotations === null) delete cleaned.annotations;
					if (cleaned.Meta === null) delete cleaned.Meta;
					if (cleaned._meta === null) delete cleaned._meta;
					return cleaned as typeof block;
				});
			}
			if (data._meta === null) delete data._meta;
			if (data.Meta === null) delete data.Meta;

			return data;
		},
		[serverId],
	);

	// Synthetic anchor activation preserves the user-gesture grant across the
	// renderer-iframe → sandbox-proxy → host postMessage hops. `window.open`
	// silently breaks on cross-origin deployments (Chrome's popup blocker)
	// even though it works on localhost.
	const onOpenLink = useCallback(async ({ url }: { url: string }) => {
		const a = document.createElement("a");
		a.href = url;
		a.target = "_blank";
		a.rel = "noopener noreferrer";
		document.body.appendChild(a);
		a.click();
		a.remove();
		return {};
	}, []);

	// AppRenderer registers no `ui/request-display-mode` handler, so it lands here.
	const onFallbackRequest = useCallback(
		async (request: JSONRPCRequest) => {
			const mode = (request.params as { mode?: McpUiDisplayMode } | undefined)?.mode;
			if (request.method === "ui/request-display-mode" && mode) {
				return { mode: onRequestDisplayMode?.(mode) ?? displayMode };
			}
			throw new McpError(
				ErrorCode.MethodNotFound,
				`No handler for method: ${request.method}`,
			);
		},
		[onRequestDisplayMode, displayMode],
	);

	if (typeof window === "undefined") {
		return null;
	}

	return (
		<div
			className={cn(
				"w-full min-w-0 overflow-hidden",
				displayMode === "fullscreen"
					? // The panel owns the height: the app fills it, whatever size it asks for.
						"flex min-h-0 flex-1 flex-col [&_iframe]:w-full! [&_iframe]:max-w-full! [&_iframe]:h-full! [&_iframe]:flex-1"
					: // AppRenderer has no autoResize option and writes iframe.style.height
						// directly in response to `onsizechange`. When the app's body uses
						// `height: 100%`, that resize reflows content, which re-measures and
						// posts again — an unbounded growth loop. Cap the iframe height with
						// !important so the library's inline style can't actually grow the
						// element; the handshake settles after one frame.
						"mt-2 [&_iframe]:w-full! [&_iframe]:max-w-full! [&_iframe]:max-h-[70vh]!",
				className,
			)}
		>
			{/* Dev-only gotcha: React StrictMode (Next dev default) double-mounts,
			    and @mcp-ui/client 7.1.1 can't survive it — AppRenderer tears down its
			    host↔app transport mid-connect, surfacing protocol.ts "Not connected"
			    and leaving the app stuck on Metabase's "press Run" state. Renders fine
			    in production builds; tracked upstream. */}
			<AppRenderer
				toolName={toolName}
				toolResourceUri={appToolInfo.resourceUri}
				sandbox={sandboxConfig}
				hostContext={hostContext}
				hostInfo={HOST_INFO}
				hostCapabilities={HOST_CAPABILITIES}
				toolInput={effectiveToolInput}
				toolResult={toolResult}
				onReadResource={onReadResource}
				onCallTool={onCallTool}
				onOpenLink={onOpenLink}
				onFallbackRequest={onFallbackRequest}
			/>
		</div>
	);
};

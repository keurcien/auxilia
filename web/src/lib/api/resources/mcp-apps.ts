/**
 * MCP-app host resource — what an embedded MCP app UI may ask its server for,
 * proxied through the backend so the app never holds credentials
 * (`app/mcp/apps/`).
 *
 * Results are MCP payloads (`CallToolResult`, `ReadResourceResult`) whose
 * `structuredContent` and resource `contents` are tool-authored JSON — the
 * key spelling is data. They go through `protocolFetch`, not the axios
 * client, so nothing is case-converted on the way to the app iframe.
 */
import type { CallToolResult, ReadResourceResult } from "@modelcontextprotocol/sdk/types.js";

import { API_BASE_URL } from "@/lib/api/client";
import { ApiError, toApiError } from "@/lib/api/errors";
import { protocolFetch } from "@/lib/api/protocol";

async function postMcpApp<T>(serverId: string, action: string, body: unknown): Promise<T> {
	let response: Response;
	try {
		response = await protocolFetch(
			`${API_BASE_URL}/mcp-servers/${encodeURIComponent(serverId)}/app/${action}`,
			{
				method: "POST",
				headers: { "content-type": "application/json" },
				body: JSON.stringify(body),
			},
		);
	} catch (error) {
		// Network failure or abort: same typed contract as an HTTP failure.
		throw toApiError(error);
	}
	const payload: unknown = await response.json().catch(() => null);
	if (!response.ok) {
		throw new ApiError({ status: response.status, body: payload });
	}
	return payload as T;
}

/** `resources/read` against the server, as the app UI requests it. */
export function readMcpAppResource(serverId: string, uri: string): Promise<ReadResourceResult> {
	return postMcpApp<ReadResourceResult>(serverId, "read-resource", { uri });
}

/** `tools/call` against the server on the app's behalf. The result comes back
 * as the backend serialised it — `null`s for absent optional fields included,
 * which the renderer rejects; the caller strips them. */
export function callMcpAppTool(
	serverId: string,
	toolName: string,
	args: Record<string, unknown> | null,
): Promise<CallToolResult> {
	// The backend body is snake_case by hand: no axios conversion on this path.
	return postMcpApp<CallToolResult>(serverId, "call-tool", { tool_name: toolName, arguments: args });
}

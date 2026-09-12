/**
 * MCP-app host resource — what an embedded MCP app UI may ask its server for,
 * proxied through the backend so the app never holds credentials
 * (`app/mcp/apps/`). Bodies are MCP-shaped; the axios client preserves the
 * `arguments` key so tool inputs reach the server as authored.
 */
import type { CallToolResult, ReadResourceResult } from "@modelcontextprotocol/sdk/types.js";

import { api } from "@/lib/api/client";

/** `resources/read` against the server, as the app UI requests it. */
export async function readMcpAppResource(
	serverId: string,
	uri: string,
): Promise<ReadResourceResult> {
	const response = await api.post<ReadResourceResult>(
		`/mcp-servers/${serverId}/app/read-resource`,
		{ uri },
	);
	return response.data;
}

/** `tools/call` against the server on the app's behalf. The result comes back
 * as the backend serialised it — `null`s for absent optional fields included,
 * which the renderer rejects; the caller strips them. */
export async function callMcpAppTool(
	serverId: string,
	toolName: string,
	args: Record<string, unknown> | null,
): Promise<CallToolResult> {
	const response = await api.post<CallToolResult>(
		`/mcp-servers/${serverId}/app/call-tool`,
		{ toolName, arguments: args },
	);
	return response.data;
}

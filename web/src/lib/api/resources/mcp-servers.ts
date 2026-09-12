/**
 * MCP server resource — `/mcp-servers` and the per-user connection probes.
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to `mcp-servers-store`.
 */
import { api } from "@/lib/api/client";
import type { BoundAgent, ToolStatus } from "@/types/agents";
import type {
	ConnectionTestResult,
	ListToolsResult,
	MCPAuthType,
	MCPCatalogSyncResult,
	MCPServer,
	MCPServerConnection,
	MCPServerCreate,
	MCPServerUpdate,
	OAuthSecretHint,
	OfficialMCPServer,
} from "@/types/mcp-servers";

export async function listMcpServers(): Promise<MCPServer[]> {
	const response = await api.get<MCPServer[]>("/mcp-servers");
	return response.data;
}

/** One server. `cookie` forwards the session from a server component. */
export async function getMcpServer(
	serverId: string,
	options: { cookie?: string } = {},
): Promise<MCPServer> {
	const response = await api.get<MCPServer>(`/mcp-servers/${serverId}`, {
		headers: options.cookie ? { Cookie: options.cookie } : undefined,
	});
	return response.data;
}

export async function createMcpServer(payload: MCPServerCreate): Promise<MCPServer> {
	const response = await api.post<MCPServer>("/mcp-servers", payload);
	return response.data;
}

export async function updateMcpServer(
	serverId: string,
	payload: MCPServerUpdate,
): Promise<MCPServer> {
	const response = await api.patch<MCPServer>(`/mcp-servers/${serverId}`, payload);
	return response.data;
}

/** Delete a server. Refused while agents still bind it unless `detachAgents`. */
export async function deleteMcpServer(
	serverId: string,
	options: { detachAgents?: boolean } = {},
): Promise<void> {
	await api.delete(`/mcp-servers/${serverId}`, {
		params: options.detachAgents ? { detachAgents: true } : undefined,
	});
}

/** Drop every user's stored OAuth connection to the server. */
export async function resetMcpServerConnections(serverId: string): Promise<void> {
	await api.post(`/mcp-servers/${serverId}/reset`);
}

/** Agents still bound to the server — the delete-guard dialog lists them. */
export async function listMcpServerAgents(serverId: string): Promise<BoundAgent[]> {
	const response = await api.get<BoundAgent[]>(`/mcp-servers/${serverId}/agents`);
	return response.data;
}

/** The server's tools for the caller, or the OAuth URL to open first (both 200). */
export async function listMcpServerTools(serverId: string): Promise<ListToolsResult> {
	const response = await api.get<ListToolsResult>(`/mcp-servers/${serverId}/list-tools`);
	return response.data;
}

/** Whether the caller's OAuth connection to the server is live. */
export async function isMcpServerConnected(serverId: string): Promise<boolean> {
	const response = await api.get<{ connected: boolean }>(
		`/mcp-servers/${serverId}/is-connected`,
	);
	return Boolean(response.data.connected);
}

/** The stored OAuth client secret, masked (admin only). */
export async function getMcpServerOAuthSecretHint(
	serverId: string,
	options: { signal?: AbortSignal } = {},
): Promise<OAuthSecretHint> {
	const response = await api.get<OAuthSecretHint>(
		`/mcp-servers/${serverId}/oauth-secret-hint`,
		{ signal: options.signal },
	);
	return response.data;
}

/** Every user's stored OAuth connection to the server (admin view). */
export async function listMcpServerConnections(
	serverId: string,
): Promise<MCPServerConnection[]> {
	const response = await api.get<MCPServerConnection[]>(
		`/mcp-servers/${serverId}/connections`,
	);
	return response.data;
}

export async function deleteMcpServerConnection(
	serverId: string,
	userId: string,
): Promise<void> {
	await api.delete(`/mcp-servers/${serverId}/connections/${userId}`);
}

/** Probe a saved server as the caller (may answer with an OAuth URL). */
export async function testMcpServerConnection(
	serverId: string,
): Promise<ConnectionTestResult> {
	const response = await api.post<ConnectionTestResult>(
		`/mcp-servers/${serverId}/test-connection`,
	);
	return response.data;
}

export interface ConnectionTestInput {
	url: string;
	authType: MCPAuthType;
	apiKey?: string;
}

/** Probe a server that is not saved yet (the add form). */
export async function testMcpConnection(
	input: ConnectionTestInput,
): Promise<ConnectionTestResult> {
	const response = await api.post<ConnectionTestResult>(
		"/mcp-servers/test-connection",
		input,
	);
	return response.data;
}

/** The official catalog (CDN-hosted YAML, mirrored by the backend). */
export async function listOfficialMcpServers(
	options: { signal?: AbortSignal } = {},
): Promise<OfficialMCPServer[]> {
	const response = await api.get<OfficialMCPServer[]>("/mcp-servers/official", {
		signal: options.signal,
	});
	return response.data;
}

/** Re-fetch the official catalog now (admin). */
export async function syncMcpCatalog(): Promise<MCPCatalogSyncResult> {
	const response = await api.post<MCPCatalogSyncResult>("/mcp-servers/catalog/sync");
	return response.data;
}

/** The persisted agent ↔ server binding, as `sync-tools` returns it. */
export interface AgentMcpServerBinding {
	agentId: string;
	mcpServerId: string;
	tools: Record<string, ToolStatus> | null;
}

/**
 * Re-read the server's tools and merge them into the agent's saved tool map
 * (editor-gated). Lives here rather than on the agent resource because it is
 * the MCP binding's own endpoint.
 */
export async function syncAgentMcpServerTools(
	agentId: string,
	serverId: string,
): Promise<AgentMcpServerBinding> {
	const response = await api.post<AgentMcpServerBinding>(
		`/agents/${agentId}/mcp-servers/${serverId}/sync-tools`,
	);
	return response.data;
}

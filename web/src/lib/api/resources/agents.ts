/**
 * Agent resource — workspace agents and their complete editable config.
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 */
import { api } from "@/lib/api/client";
import type { ThreadResourceSettings } from "@/types/threads";
import type { Paginated } from "@/types/api";
import type {
	Agent,
	AgentPermission,
	AgentResources,
	AgentSlackBotSettings,
	AgentSlackBotSettingsUpdate,
	AgentTelegramBotSettings,
	AgentTelegramBotSettingsUpdate,
	AgentWhatsAppSettings,
	AgentWhatsAppSettingsUpdate,
	ToolDiscoveryMode,
} from "@/types/agents";
import type { ResourceVisibility } from "@/types/visibility";

/** `POST /agents` and `PUT /agents/{id}/config` share this body (see
 * `agent-form.ts::toPayload`). */
export interface AgentWrite {
	name: string;
	instructions: string;
	description: string | null;
	group: string | null;
	emoji: string | null;
	color: string | null;
	visibility: ResourceVisibility;
	webSearchEnabled?: boolean;
	toolDiscoveryMode?: ToolDiscoveryMode;
	defaultModelId?: string | null;
	defaultReasoningEffort?: string | null;
	teamIds: string[];
	mcpServers: {
		mcpServerId: string;
		enabledByDefault: boolean;
		tools: Record<string, string> | null;
	}[];
	sandboxes: {
		sandboxId: string;
		enabledByDefault: boolean;
		tools: Record<string, string> | null;
	}[];
	subagentIds: string[];
	disabledSubagentIdsByDefault?: string[];
	skillIds: string[];
	disabledSkillIdsByDefault?: string[];
}

/** Fields `PATCH /agents/{id}` accepts outside the config draft. */
export interface AgentPatch {
	group?: string | null;
	toolDiscoveryMode?: ToolDiscoveryMode;
}

export type AgentReadyStatus =
	| "ready"
	| "not_configured"
	| "disconnected"
	| "sandbox_unavailable";

/** `GET /agents/{id}/is-ready` reports LLM usability and optional resource health. */
export interface AgentReadiness {
	ready: boolean;
	acceptsFiles: boolean;
	disconnectedServers: string[];
	status: AgentReadyStatus;
	/** Human-readable reason for a resource warning, when available. */
	detail?: string | null;
}

/** A grant row on the agent — everything but `owner`, which is derived. */
export type GrantLevel = Exclude<AgentPermission, "owner">;

export interface AgentPermissionRow {
	userId: string;
	permission: GrantLevel;
}

/** The workspace's agents visible to the caller (slim rows). */
export async function listAgents(
	options: { cookie?: string } = {},
): Promise<Agent[]> {
	const response = options.cookie
		? await api.get<Agent[]>("/agents/", {
				headers: { Cookie: options.cookie },
			})
		: await api.get<Agent[]>("/agents");
	return response.data;
}

/** Archived agents — owners/admins only see theirs, per the backend. */
export async function listArchivedAgents(): Promise<Agent[]> {
	const response = await api.get<Agent[]>("/agents", { params: { archived: true } });
	return response.data;
}

/** One agent, with instructions and the full tools map. `cookie` forwards
 * the session from a server component. */
export async function getAgent(
	agentId: string,
	options: { cookie?: string } = {},
): Promise<Agent> {
	const response = await api.get<Agent>(`/agents/${agentId}`, {
		headers: options.cookie ? { Cookie: options.cookie } : undefined,
	});
	return response.data;
}

export async function getAgentResources(
	agentId: string,
): Promise<AgentResources> {
	const response = await api.get<AgentResources>(`/agents/${agentId}/resources`);
	return response.data;
}

export async function createAgent(payload: AgentWrite): Promise<Agent> {
	const response = await api.post<Agent>("/agents", payload);
	return response.data;
}

/** Atomic replace of the editable configuration. */
export async function saveAgentConfig(agentId: string, payload: AgentWrite): Promise<Agent> {
	const response = await api.put<Agent>(`/agents/${agentId}/config`, payload);
	return response.data;
}

/** A resource that can be enabled on an agent one at a time. */
export type AttachableResource = "mcpServer" | "skill" | "subagent";

const ATTACH_PATHS: Record<AttachableResource, string> = {
	mcpServer: "mcp-servers",
	skill: "skills",
	subagent: "subagents",
};

/** Enable one resource on an agent without resending its whole config.
 * Idempotent: an existing binding is left as it is (MCP: its default is updated). */
export async function attachToAgent(
	agentId: string,
	kind: AttachableResource,
	resourceId: string,
	options: { enabledByDefault: boolean },
): Promise<void> {
	await api.post(`/agents/${agentId}/${ATTACH_PATHS[kind]}/${resourceId}`, {
		enabledByDefault: options.enabledByDefault,
	});
}

export function agentImageUrl(agentId: string, revision: string): string {
	return `/api/backend/agents/${agentId}/image?v=${encodeURIComponent(revision)}`;
}

export async function uploadAgentImage(agentId: string, file: File): Promise<string> {
	const form = new FormData();
	form.append("file", file);
	const response = await api.put<{ imageRevision: string }>(
		`/agents/${agentId}/image`,
		form,
	);
	return response.data.imageRevision;
}

export async function deleteAgentImage(agentId: string): Promise<void> {
	await api.delete(`/agents/${agentId}/image`);
}

export async function patchAgent(agentId: string, patch: AgentPatch): Promise<Agent> {
	const response = await api.patch<Agent>(`/agents/${agentId}`, patch);
	return response.data;
}

/** Make this agent the single workspace default. */
export async function setDefaultAgent(agentId: string): Promise<Agent> {
	const response = await api.put<Agent>(`/agents/${agentId}/default`);
	return response.data;
}

/** Clear this agent as the workspace default. */
export async function clearDefaultAgent(agentId: string): Promise<Agent> {
	const response = await api.delete<Agent>(`/agents/${agentId}/default`);
	return response.data;
}

/** Soft delete — the agent moves to the archive. */
export async function archiveAgent(agentId: string): Promise<void> {
	await api.delete(`/agents/${agentId}`);
}

export async function restoreAgent(agentId: string): Promise<void> {
	await api.post(`/agents/${agentId}/restore`);
}

/** Hard delete — the agent, its bindings and every thread that used it. */
export async function permanentlyDeleteAgent(agentId: string): Promise<void> {
	await api.delete(`/agents/${agentId}/permanent`);
}

export async function getAgentReadiness(
	agentId: string,
	resources?: ThreadResourceSettings,
): Promise<AgentReadiness> {
	const params = resources
		? {
				disabledMcpServerIds: resources.disabledMcpServerIds,
				disabledSandboxIds: resources.disabledSandboxIds,
				disabledSubagentIds: resources.disabledSubagentIds,
				toolMode: resources.toolMode,
			}
		: undefined;
	const response = resources
		? await api.get<AgentReadiness>(`/agents/${agentId}/is-ready`, { params })
		: await api.get<AgentReadiness>(`/agents/${agentId}/is-ready`);
	return response.data;
}

export async function listAgentSlackBots(
	agentId: string,
): Promise<AgentSlackBotSettings[]> {
	const response = await api.get<AgentSlackBotSettings[]>(
		`/agents/${agentId}/integrations/slack`,
	);
	return response.data;
}

export async function getAgentSlackBotSetup(
	agentId: string,
): Promise<AgentSlackBotSettings> {
	const response = await api.get<AgentSlackBotSettings>(
		`/agents/${agentId}/integrations/slack/setup`,
	);
	return response.data;
}

export async function createAgentSlackBot(
	agentId: string,
	update: AgentSlackBotSettingsUpdate,
): Promise<AgentSlackBotSettings> {
	const response = await api.post<AgentSlackBotSettings>(
		`/agents/${agentId}/integrations/slack`,
		update,
	);
	return response.data;
}

export async function updateAgentSlackBot(
	agentId: string,
	botId: string,
	update: AgentSlackBotSettingsUpdate,
): Promise<AgentSlackBotSettings> {
	const response = await api.put<AgentSlackBotSettings>(
		`/agents/${agentId}/integrations/slack/${botId}`,
		update,
	);
	return response.data;
}

export async function deleteAgentSlackBot(
	agentId: string,
	botId: string,
): Promise<void> {
	await api.delete(`/agents/${agentId}/integrations/slack/${botId}`);
}

export async function listAgentTelegramBots(
	agentId: string,
): Promise<AgentTelegramBotSettings[]> {
	const response = await api.get<AgentTelegramBotSettings[]>(
		`/agents/${agentId}/integrations/telegram`,
	);
	return response.data;
}

export async function getAgentTelegramBotSetup(
	agentId: string,
): Promise<AgentTelegramBotSettings> {
	const response = await api.get<AgentTelegramBotSettings>(
		`/agents/${agentId}/integrations/telegram/setup`,
	);
	return response.data;
}

export async function createAgentTelegramBot(
	agentId: string,
	update: AgentTelegramBotSettingsUpdate,
): Promise<AgentTelegramBotSettings> {
	const response = await api.post<AgentTelegramBotSettings>(
		`/agents/${agentId}/integrations/telegram`,
		update,
	);
	return response.data;
}

export async function updateAgentTelegramBot(
	agentId: string,
	botId: string,
	update: AgentTelegramBotSettingsUpdate,
): Promise<AgentTelegramBotSettings> {
	const response = await api.put<AgentTelegramBotSettings>(
		`/agents/${agentId}/integrations/telegram/${botId}`,
		update,
	);
	return response.data;
}

export async function deleteAgentTelegramBot(
	agentId: string,
	botId: string,
): Promise<void> {
	await api.delete(`/agents/${agentId}/integrations/telegram/${botId}`);
}

export async function listAgentWhatsAppConnections(
	agentId: string,
): Promise<AgentWhatsAppSettings[]> {
	const response = await api.get<AgentWhatsAppSettings[]>(
		`/agents/${agentId}/integrations/whatsapp`,
	);
	return response.data;
}

export async function getAgentWhatsAppSetup(
	agentId: string,
): Promise<AgentWhatsAppSettings> {
	const response = await api.get<AgentWhatsAppSettings>(
		`/agents/${agentId}/integrations/whatsapp/setup`,
	);
	return response.data;
}

export async function createAgentWhatsAppConnection(
	agentId: string,
	update: AgentWhatsAppSettingsUpdate,
): Promise<AgentWhatsAppSettings> {
	const response = await api.post<AgentWhatsAppSettings>(
		`/agents/${agentId}/integrations/whatsapp`,
		update,
	);
	return response.data;
}

export async function updateAgentWhatsAppConnection(
	agentId: string,
	connectionId: string,
	update: AgentWhatsAppSettingsUpdate,
): Promise<AgentWhatsAppSettings> {
	const response = await api.put<AgentWhatsAppSettings>(
		`/agents/${agentId}/integrations/whatsapp/${connectionId}`,
		update,
	);
	return response.data;
}

export async function deleteAgentWhatsAppConnection(
	agentId: string,
	connectionId: string,
): Promise<void> {
	await api.delete(
		`/agents/${agentId}/integrations/whatsapp/${connectionId}`,
	);
}

export async function listAgentPermissions(agentId: string): Promise<AgentPermissionRow[]> {
	const response = await api.get<AgentPermissionRow[]>(`/agents/${agentId}/permissions`);
	return response.data;
}

/** Whole-set replace of the per-user grants. */
export async function setAgentPermissions(
	agentId: string,
	rows: AgentPermissionRow[],
): Promise<void> {
	await api.put(`/agents/${agentId}/permissions`, rows);
}

export async function listAgentTeamIds(agentId: string): Promise<string[]> {
	const response = await api.get<{ teamIds: string[] }>(`/agents/${agentId}/teams`);
	return response.data.teamIds;
}

/** Whole-set replace of the teams whose members get `member` access. */
export async function setAgentTeamIds(agentId: string, teamIds: string[]): Promise<void> {
	await api.put(`/agents/${agentId}/teams`, { teamIds });
}

// Re-exported so callers that only need the page shape import one module.
export type { Paginated };

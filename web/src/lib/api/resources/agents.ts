/**
 * Agent resource — `/agents` and the `/tags` vocabulary agents are grouped by.
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 */
import { api } from "@/lib/api/client";
import type { Paginated } from "@/types/api";
import type { Agent, AgentPermission, AgentTag } from "@/types/agents";

/** `POST /agents` and `PUT /agents/{id}/config` share this body (see
 * `agent-form.ts::toPayload`). */
export interface AgentWrite {
	name: string;
	instructions: string;
	description: string | null;
	emoji: string | null;
	color: string | null;
	mcpServers: { mcpServerId: string; tools: Record<string, string> | null }[];
	sandboxes: { sandboxId: string; tools: Record<string, string> | null }[];
	subagentIds: string[];
}

/** Fields `PATCH /agents/{id}` accepts outside the config draft. */
export interface AgentPatch {
	tagId?: string | null;
}

export type AgentReadyStatus = "ready" | "not_configured" | "disconnected";

/** `GET /agents/{id}/is-ready` — can the agent run right now? */
export interface AgentReadiness {
	ready: boolean;
	disconnectedServers: string[];
	status: AgentReadyStatus;
}

/** A grant row on the agent — everything but `owner`, which is derived. */
export type GrantLevel = Exclude<AgentPermission, "owner">;

export interface AgentPermissionRow {
	userId: string;
	permission: GrantLevel;
}

/** The workspace's agents visible to the caller (slim rows). */
export async function listAgents(): Promise<Agent[]> {
	const response = await api.get<Agent[]>("/agents");
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

export async function createAgent(payload: AgentWrite): Promise<Agent> {
	const response = await api.post<Agent>("/agents", payload);
	return response.data;
}

/** Atomic replace of the editable configuration. */
export async function saveAgentConfig(agentId: string, payload: AgentWrite): Promise<Agent> {
	const response = await api.put<Agent>(`/agents/${agentId}/config`, payload);
	return response.data;
}

export async function patchAgent(agentId: string, patch: AgentPatch): Promise<Agent> {
	const response = await api.patch<Agent>(`/agents/${agentId}`, patch);
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

export async function getAgentReadiness(agentId: string): Promise<AgentReadiness> {
	const response = await api.get<AgentReadiness>(`/agents/${agentId}/is-ready`);
	return response.data;
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

// --- tags ------------------------------------------------------------------

export async function listTags(): Promise<AgentTag[]> {
	const response = await api.get<AgentTag[]>("/tags/");
	return response.data;
}

export async function createTag(name: string): Promise<AgentTag> {
	const response = await api.post<AgentTag>("/tags/", { name });
	return response.data;
}

export async function renameTag(tagId: string, name: string): Promise<AgentTag> {
	const response = await api.patch<AgentTag>(`/tags/${tagId}`, { name });
	return response.data;
}

/** Agents carrying the tag become untagged. */
export async function deleteTag(tagId: string): Promise<void> {
	await api.delete(`/tags/${tagId}`);
}

// Re-exported so callers that only need the page shape import one module.
export type { Paginated };

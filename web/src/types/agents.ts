import { MCPServer } from "./mcp-servers";

export type ToolStatus = "always_allow" | "needs_approval" | "disabled";

interface AgentMCPServer extends MCPServer {
	mcpServerId: string;
	tools: Record<string, ToolStatus> | null;
}

export type AgentPermission = "owner" | "admin" | "editor" | "member";

export interface SubagentInfo {
	id: string;
	name: string;
	emoji?: string | null;
	color?: string | null;
	description?: string | null;
}

export interface Agent {
	id: string;
	name: string;
	instructions: string;
	ownerId: string;
	emoji?: string | null;
	color?: string | null;
	description?: string | null;
	hasCodeInterpreter: boolean;
	mcpServers: AgentMCPServer[];
	subagents: SubagentInfo[];
	isSubagent: boolean;
	currentUserPermission?: AgentPermission | null;
}

export interface AgentMCPServerDraft {
	mcpServerId: string;
	tools: Record<string, ToolStatus> | null;
}

// In-memory copy of the editable agent config. Created on "Edit", mutated by
// the editor and its children, sent as one PUT /agents/{id}/config on "Save".
export interface AgentDraft {
	name: string;
	instructions: string;
	description: string;
	emoji: string | null;
	color: string | null;
	hasCodeInterpreter: boolean;
	mcpServers: AgentMCPServerDraft[];
	subagents: SubagentInfo[];
}

export type AgentDraftUpdater = (prev: AgentDraft) => AgentDraft;

export function buildAgentDraft(agent: Agent): AgentDraft {
	return {
		name: agent.name || "",
		instructions: agent.instructions || "",
		description: agent.description || "",
		emoji: agent.emoji ?? null,
		color: agent.color ?? null,
		hasCodeInterpreter: agent.hasCodeInterpreter,
		mcpServers: (agent.mcpServers || []).map((s) => ({
			mcpServerId: s.mcpServerId,
			tools: s.tools ? { ...s.tools } : null,
		})),
		subagents: (agent.subagents || []).map((s) => ({ ...s })),
	};
}

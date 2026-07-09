import { MCPServer } from "./mcp-servers";

export type ToolStatus = "always_allow" | "needs_approval" | "disabled";

interface AgentMCPServer extends MCPServer {
	mcpServerId: string;
	tools: Record<string, ToolStatus> | null;
}

export type AgentPermission = "owner" | "admin" | "editor" | "member";

/** Can this viewer configure the agent (edit instructions, MCP tools)? */
export const canConfigureAgent = (permission?: AgentPermission | null): boolean =>
	permission === "owner" || permission === "admin" || permission === "editor";

interface SubagentInfo {
	id: string;
	name: string;
	emoji?: string | null;
	color?: string | null;
	description?: string | null;
}

export interface AgentTag {
	id: string;
	name: string;
}

export interface AgentOwner {
	id: string;
	name?: string | null;
	email?: string | null;
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
	isArchived: boolean;
	mcpServers: AgentMCPServer[];
	subagents: SubagentInfo[];
	tag?: AgentTag | null;
	owner?: AgentOwner | null;
	isSubagent: boolean;
	currentUserPermission?: AgentPermission | null;
}

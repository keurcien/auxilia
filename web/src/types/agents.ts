import { MCPServer } from "./mcp-servers";

export type ToolStatus = "always_allow" | "needs_approval" | "disabled";

export interface AgentMCPServer extends MCPServer {
	mcpServerId: string;
	tools: Record<string, ToolStatus> | null;
}

export type AgentPermission = "owner" | "admin" | "editor" | "user";

export interface SubagentInfo {
	id: string;
	name: string;
	emoji?: string | null;
	description?: string | null;
}

export interface Agent {
	id: string;
	name: string;
	instructions: string;
	ownerId: string;
	emoji?: string | null;
	description?: string | null;
	sandbox: boolean;
	mcpServers: AgentMCPServer[];
	subagents: SubagentInfo[];
	isSubagent: boolean;
	currentUserPermission?: AgentPermission | null;
}

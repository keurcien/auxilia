import { MCPServer } from "./mcp-servers";

export type ToolStatus = "always_allow" | "needs_approval" | "disabled";

export interface AgentMCPServer extends MCPServer {
	tools: Record<string, ToolStatus> | null;
}

export type AgentPermission = "owner" | "admin" | "editor" | "user";

export interface Agent {
	id: string;
	name: string;
	instructions: string;
	ownerId: string;
	emoji?: string | null;
	mcpServers: AgentMCPServer[];
	currentUserPermission?: AgentPermission | null;
}

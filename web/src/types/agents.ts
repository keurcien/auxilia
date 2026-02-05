import { MCPServer } from "./mcp-servers";

export type ToolStatus = "always_allow" | "needs_approval" | "disabled";

export interface AgentMCPServer extends MCPServer {
	tools: Record<string, ToolStatus> | null;
}

export interface Agent {
	id: string;
	name: string;
	instructions: string;
	emoji?: string | null;
	mcpServers: AgentMCPServer[];
}

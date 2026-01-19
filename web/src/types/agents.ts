import { MCPServer } from "./mcp-servers";

export interface AgentMCPServer extends MCPServer {
	enabledTools: string[];
}

export interface Agent {
	id: string;
	name: string;
	instructions: string;
	emoji?: string | null;
	mcpServers: AgentMCPServer[];
}

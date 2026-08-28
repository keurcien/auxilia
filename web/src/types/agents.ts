import { MCPServer } from "./mcp-servers";
import { SandboxProviderType } from "./sandboxes";

export type ToolStatus = "always_allow" | "needs_approval" | "disabled";

interface AgentMCPServer extends MCPServer {
	mcpServerId: string;
	/** Absent on list responses; the detail response carries the full map
	 * (null = never synced). */
	tools?: Record<string, ToolStatus> | null;
}

/** One agent↔sandbox binding, flattened with the sandbox's display fields. */
export interface AgentSandbox {
	sandboxId: string;
	tools: Record<string, ToolStatus> | null;
	name: string;
	provider: SandboxProviderType;
	url: string;
}

/** An agent still bound to a workspace resource (sandbox, MCP server) —
 * shown in the delete-guard dialog. */
export interface BoundAgent {
	id: string;
	name: string;
	emoji: string | null;
	color: string | null;
}

export type AgentPermission = "owner" | "admin" | "editor" | "member";

/** Can this viewer configure the agent (edit instructions, MCP tools)? */
export const canConfigureAgent = (permission?: AgentPermission | null): boolean =>
	permission === "owner" || permission === "admin" || permission === "editor";

export interface SubagentInfo {
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
	pictureUrl?: string | null;
}

export interface Agent {
	id: string;
	name: string;
	/** Absent on list responses (GET /agents returns slim rows); present on
	 * detail responses (GET /agents/{id}) and save results. */
	instructions?: string;
	ownerId: string;
	emoji?: string | null;
	color?: string | null;
	description?: string | null;
	isArchived: boolean;
	mcpServers: AgentMCPServer[];
	sandboxes: AgentSandbox[];
	subagents: SubagentInfo[];
	tag?: AgentTag | null;
	owner?: AgentOwner | null;
	isSubagent: boolean;
	currentUserPermission?: AgentPermission | null;
}

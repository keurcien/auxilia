import { Agent, ToolStatus } from "@/types/agents";
import { AGENT_COLORS, randomAgentColor } from "@/lib/colors";

export interface AgentMCPServerForm {
	mcpServerId: string;
	/** Complete per-tool map, or null = never synced (server not connected). */
	tools: Record<string, ToolStatus> | null;
}

/** The draft the agent editor works on — the client side of `AgentConfig`. */
export interface AgentFormState {
	name: string;
	description: string;
	instructions: string;
	emoji: string;
	color: string;
	hasCodeInterpreter: boolean;
	mcpServers: AgentMCPServerForm[];
	subagentIds: string[];
}

/** Blank draft for the create page (`/agents/new`). */
export function defaultAgentForm(): AgentFormState {
	return {
		name: "",
		description: "",
		instructions: "",
		emoji: "🤖",
		color: randomAgentColor(),
		hasCodeInterpreter: false,
		mcpServers: [],
		subagentIds: [],
	};
}

export function fromAgent(agent: Agent): AgentFormState {
	return {
		name: agent.name || "",
		description: agent.description || "",
		instructions: agent.instructions || "",
		emoji: agent.emoji || "🤖",
		color: agent.color || AGENT_COLORS[0],
		hasCodeInterpreter: agent.hasCodeInterpreter,
		mcpServers: (agent.mcpServers || []).map((server) => ({
			mcpServerId: server.mcpServerId,
			tools: server.tools ? { ...server.tools } : null,
		})),
		subagentIds: (agent.subagents || []).map((sub) => sub.id),
	};
}

/**
 * Canonical serializer used both as the PUT /agents/{id}/config body and for
 * dirty-checking — servers, tool keys and subagent ids are sorted so the
 * JSON comparison never trips on ordering.
 */
export function toPayload(form: AgentFormState) {
	return {
		name: form.name.trim(),
		instructions: form.instructions.trim(),
		description: form.description.trim() || null,
		emoji: form.emoji || null,
		color: form.color || null,
		hasCodeInterpreter: form.hasCodeInterpreter,
		mcpServers: [...form.mcpServers]
			.sort((a, b) => a.mcpServerId.localeCompare(b.mcpServerId))
			.map((server) => ({
				mcpServerId: server.mcpServerId,
				tools: server.tools
					? Object.fromEntries(
							Object.entries(server.tools).sort(([a], [b]) =>
								a.localeCompare(b),
							),
						)
					: null,
			})),
		subagentIds: [...form.subagentIds].sort(),
	};
}

export function isFormDirty(
	form: AgentFormState,
	initial: AgentFormState,
): boolean {
	return JSON.stringify(toPayload(form)) !== JSON.stringify(toPayload(initial));
}

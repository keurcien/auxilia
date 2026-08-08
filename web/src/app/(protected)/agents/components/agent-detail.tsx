"use client";

import { useEffect } from "react";
import { Agent } from "@/types/agents";
import AgentEditor from "./agent-editor";
import { useAgentsStore } from "@/stores/agents-store";

interface AgentDetailProps {
	agent: Agent;
}

/**
 * The agent page IS the editor (design 12a — no separate read mode).
 * Non-editors get the same two-panel layout with disabled inputs.
 */
export default function AgentDetail({ agent }: AgentDetailProps) {
	const updateAgent = useAgentsStore((state) => state.updateAgent);

	const liveAgent = useAgentsStore(
		(state) => state.agents.find((a) => a.id === agent.id) ?? agent,
	);

	// The server-rendered copy is fresher than whatever the store loaded on
	// layout mount — sync it in so the edit snapshot matches it.
	useEffect(() => {
		updateAgent(agent.id, agent);
	}, [agent, updateAgent]);

	const canEditAgent =
		liveAgent.currentUserPermission === "owner" ||
		liveAgent.currentUserPermission === "admin" ||
		liveAgent.currentUserPermission === "editor";

	return (
		<AgentEditor
			// Keyed so navigating between agents never carries draft state over.
			key={agent.id}
			agent={liveAgent}
			readOnly={!canEditAgent}
			onSaved={() => {}}
			onCancel={() => {}}
		/>
	);
}

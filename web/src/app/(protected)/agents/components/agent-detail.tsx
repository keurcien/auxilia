"use client";

import { useEffect, useState } from "react";
import { Agent } from "@/types/agents";
import AgentEditor from "./agent-editor";
import { useAgentsStore } from "@/stores/agents-store";

interface AgentDetailProps {
	agent: Agent;
}

/**
 * The agent page: the 12a two-panel layout in read mode (markdown
 * instructions, disabled inputs) with an explicit Edit button that flips
 * into the editable draft. Save/Discard return to read mode.
 */
export default function AgentDetail({ agent }: AgentDetailProps) {
	const updateAgent = useAgentsStore((state) => state.updateAgent);

	const liveAgent = useAgentsStore(
		(state) => state.agents.find((a) => a.id === agent.id) ?? agent,
	);

	const [mode, setMode] = useState<"read" | "edit">("read");

	// The server-rendered copy is fresher than whatever the store loaded on
	// layout mount — sync it in so read mode and the edit snapshot match it.
	useEffect(() => {
		updateAgent(agent.id, agent);
	}, [agent, updateAgent]);

	const canEditAgent =
		liveAgent.currentUserPermission === "owner" ||
		liveAgent.currentUserPermission === "admin" ||
		liveAgent.currentUserPermission === "editor";

	return (
		<AgentEditor
			// Keyed so navigating between agents never carries draft state over,
			// and entering edit mode snapshots the freshest agent.
			key={`${agent.id}:${mode}`}
			agent={liveAgent}
			readOnly={mode === "read"}
			onEdit={
				canEditAgent
					? () => {
							setMode("edit");
						}
					: undefined
			}
			onSaved={() => {
				setMode("read");
			}}
			onCancel={() => {
				setMode("read");
			}}
		/>
	);
}

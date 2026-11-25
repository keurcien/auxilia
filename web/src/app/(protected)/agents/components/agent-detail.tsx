"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Agent } from "@/types/agents";
import AgentEditor, {
	type CapabilityTab,
	type EditorTab,
} from "./agent-editor";
import { useAgentsStore } from "@/stores/agents-store";

interface AgentDetailProps {
	agent: Agent;
	/** `?edit=1` from an Edit link; ignored when the viewer can't edit. */
	startInEdit?: boolean;
}

/**
 * The agent page: the 12a two-panel layout in read mode (markdown
 * instructions, disabled inputs) with an explicit Edit button that flips
 * into the editable draft. Save/Discard return to read mode.
 */
export default function AgentDetail({
	agent,
	startInEdit = false,
}: AgentDetailProps) {
	const router = useRouter();
	const updateAgent = useAgentsStore((state) => state.updateAgent);

	const storeAgent = useAgentsStore((state) =>
		state.agents.find((a) => a.id === agent.id),
	);

	// The list fetch stores slim rows (no instructions / tool maps), and the
	// editor snapshots its form from the first agent it renders with — so a
	// slim copy must never reach it (a save would wipe the missing fields).
	// Use the store copy only once it's full (merged below or written back by
	// a save). After a realtime list refresh it becomes slim again: overlay its
	// fresh list fields (notably `isDefault`) onto the server-rendered detail,
	// while retaining fields the list deliberately omits.
	const liveAgent = useMemo(() => {
		if (!storeAgent) return agent;
		if (storeAgent.instructions !== undefined) return storeAgent;
		return {
			...agent,
			...storeAgent,
			instructions: agent.instructions,
			mcpServers: agent.mcpServers,
			sandboxes: agent.sandboxes,
			skills: agent.skills,
			toolDiscoveryMode: agent.toolDiscoveryMode,
			defaultModelId: agent.defaultModelId,
			defaultReasoningEffort: agent.defaultReasoningEffort,
		};
	}, [storeAgent, agent]);

	const [tab, setTab] = useState<EditorTab>("instructions");
	const [capabilityTab, setCapabilityTab] = useState<CapabilityTab>("mcp");

	// The server-rendered copy is fresher than whatever the store loaded on
	// layout mount — sync it in so read mode and the edit snapshot match it.
	useEffect(() => {
		updateAgent(agent.id, agent);
	}, [agent, updateAgent]);

	const canEditAgent =
		liveAgent.currentUserPermission === "owner" ||
		liveAgent.currentUserPermission === "admin" ||
		liveAgent.currentUserPermission === "editor";

	const [mode, setMode] = useState<"read" | "edit">(
		startInEdit && canEditAgent ? "edit" : "read",
	);
	const leaveEdit = () => {
		setMode("read");
		if (startInEdit) router.replace(`/agents/${agent.id}`);
	};

	return (
		<AgentEditor
			// Keyed so navigating between agents never carries draft state over,
			// and entering edit mode snapshots the freshest agent.
			key={`${agent.id}:${mode}`}
			agent={liveAgent}
			readOnly={mode === "read"}
			initialTab={tab}
			onTabChange={setTab}
			initialCapabilityTab={capabilityTab}
			onCapabilityTabChange={setCapabilityTab}
			onEdit={
				canEditAgent
					? () => {
							setMode("edit");
						}
					: undefined
			}
			onSaved={leaveEdit}
			onCancel={leaveEdit}
		/>
	);
}

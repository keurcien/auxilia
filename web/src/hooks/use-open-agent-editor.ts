"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAgentsStore } from "@/stores/agents-store";
import { canConfigureAgent } from "@/types/agents";

/** Copy for the "No access" dialog shown when the gate below refuses. */
export const AGENT_EDITOR_FORBIDDEN_MESSAGE =
	"You don't have permission to configure this agent. Ask the agent's owner or a workspace admin to grant you editor access.";

/**
 * Navigation to an agent's editor page (`/agents/{id}`), gated the way the
 * agent list gates its cards — except the bar is `editor`: the viewer must be
 * able to configure the agent (owner and workspace admin resolve higher), or
 * a "No access" dialog explains instead of a silent no-op.
 *
 * The permission comes from the agents store, which the sidebar loads on
 * every protected page; the hook still asks for the load so a deep link works
 * before the sidebar has. An agent the store doesn't know (archived, deleted,
 * or not yet loaded) is treated as not accessible.
 */
export function useOpenAgentEditor() {
	const router = useRouter();
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	useEffect(() => {
		fetchAgents().catch(() => {});
	}, [fetchAgents]);

	const openAgentEditor = useCallback(
		(agentId: string) => {
			const permission = useAgentsStore
				.getState()
				.agents.find((a) => a.id === agentId)?.currentUserPermission;
			if (!canConfigureAgent(permission)) {
				setForbiddenOpen(true);
				return;
			}
			router.push(`/agents/${agentId}`);
		},
		[router],
	);

	return { openAgentEditor, forbiddenOpen, setForbiddenOpen };
}

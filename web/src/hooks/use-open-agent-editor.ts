"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAgentsStore } from "@/stores/agents-store";
import { canConfigureAgent } from "@/types/agents";

/** Copy for the "No access" dialog shown when the gate below refuses. */
export const AGENT_EDITOR_FORBIDDEN_MESSAGE =
	"You don't have permission to configure this agent. Ask the agent's owner or a workspace admin to grant you editor access.";

interface OpenAgentEditorOptions {
	/** Runs once access is confirmed, right before navigating; return false to
	 * stay on the page (the editor uses it to guard an unsaved draft). */
	beforeNavigate?: () => boolean;
}

/**
 * Navigation to an agent's editor page (`/agents/{id}`), gated the way the
 * agent list gates its cards — except the bar is `editor`: the viewer must be
 * able to configure the agent (owner and workspace admin resolve higher), or
 * a "No access" dialog explains instead of a silent no-op.
 *
 * The permission comes from the agents store, which the sidebar loads on
 * every protected page. A click that lands before that first load settles
 * waits for it rather than reading an empty list as a refusal. An agent the
 * loaded store doesn't know (archived, deleted) is treated as not accessible.
 */
export function useOpenAgentEditor() {
	const router = useRouter();
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	useEffect(() => {
		fetchAgents().catch(() => {});
	}, [fetchAgents]);

	const openAgentEditor = useCallback(
		async (agentId: string, { beforeNavigate }: OpenAgentEditorOptions = {}) => {
			if (!useAgentsStore.getState().isInitialized) {
				await fetchAgents().catch(() => {});
			}
			const permission = useAgentsStore
				.getState()
				.agents.find((a) => a.id === agentId)?.currentUserPermission;
			if (!canConfigureAgent(permission)) {
				setForbiddenOpen(true);
				return;
			}
			if (beforeNavigate && !beforeNavigate()) return;
			router.push(`/agents/${agentId}`);
		},
		[fetchAgents, router],
	);

	return { openAgentEditor, forbiddenOpen, setForbiddenOpen };
}

"use client";

import { Trigger } from "@/types/triggers";
import { useTriggersStore } from "@/stores/triggers-store";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useAgentsStore } from "@/stores/agents-store";
import { useActiveRunsStore } from "@/stores/active-runs-store";

/**
 * Fires a trigger manually and surfaces the new thread in the sidebar,
 * where the active-runs poll picks up its loading state. No navigation —
 * the run works in the background. Errors bubble to the caller.
 */
export function useRunTrigger() {
	const runTrigger = useTriggersStore((state) => state.runTrigger);
	const addRun = useTriggerRunsStore((state) => state.addRun);
	const addThread = useThreadsStore((state) => state.addThread);
	const agents = useAgentsStore((state) => state.agents);
	const markThreadRunning = useActiveRunsStore(
		(state) => state.markThreadRunning,
	);

	return async (trigger: Trigger) => {
		const { threadId } = await runTrigger(trigger.id);
		// Spinner from the first frame — the poll confirms right after.
		markThreadRunning(threadId);
		// Mirror the thread the backend just created (one fresh thread per
		// firing, titled after the trigger) instead of re-fetching it.
		const agent = agents.find((a) => a.id === trigger.agentId);
		const createdAt = new Date().toISOString();
		addThread({
			id: threadId,
			agentId: trigger.agentId,
			userId: trigger.ownerId,
			firstMessageContent: trigger.name,
			agentName: agent?.name ?? null,
			agentEmoji: agent?.emoji ?? null,
			agentColor: agent?.color ?? null,
			agentArchived: false,
			source: "trigger",
			triggerId: trigger.id,
			createdAt,
		});
		addRun(trigger.id, {
			id: threadId,
			agentId: trigger.agentId,
			firstMessageContent: trigger.name,
			createdAt,
		});
	};
}

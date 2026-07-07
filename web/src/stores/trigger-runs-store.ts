import { create } from "zustand";
import { TriggerThread } from "@/types/triggers";
import { RunTerminalStatus } from "@/types/runs";
import { api } from "@/lib/api/client";

interface TriggerRunsState {
	/** Past firings (threads) per trigger id; undefined = not fetched yet. */
	runsByTrigger: Record<string, TriggerThread[]>;
	fetchRuns: (triggerId: string) => Promise<void>;
	addRun: (triggerId: string, run: TriggerThread) => void;
	removeRun: (threadId: string) => void;
	/** Stamp a run outcome observed by the active-runs poll (Failed marker). */
	setRunStatus: (threadId: string, status: RunTerminalStatus) => void;
}

export const useTriggerRunsStore = create<TriggerRunsState>((set) => ({
	runsByTrigger: {},
	fetchRuns: async (triggerId) => {
		try {
			const response = await api.get<TriggerThread[]>(
				`/triggers/${triggerId}/threads`,
			);
			set((state) => ({
				runsByTrigger: {
					...state.runsByTrigger,
					[triggerId]: response.data,
				},
			}));
		} catch (error) {
			console.error("Error fetching trigger runs:", error);
			throw error;
		}
	},
	addRun: (triggerId, run) => {
		set((state) => ({
			runsByTrigger: {
				...state.runsByTrigger,
				[triggerId]: [run, ...(state.runsByTrigger[triggerId] ?? [])],
			},
		}));
	},
	removeRun: (threadId) => {
		set((state) => ({
			runsByTrigger: Object.fromEntries(
				Object.entries(state.runsByTrigger).map(([triggerId, runs]) => [
					triggerId,
					runs.filter((run) => run.id !== threadId),
				]),
			),
		}));
	},
	setRunStatus: (threadId, status) => {
		set((state) => {
			// A firing belongs to exactly one trigger — rebuild only that
			// entry so unrelated run-history cards keep their references.
			for (const [triggerId, runs] of Object.entries(state.runsByTrigger)) {
				const index = runs.findIndex((run) => run.id === threadId);
				if (index === -1) continue;
				if (runs[index].lastRunStatus === status) return state;
				const next = runs.slice();
				next[index] = { ...runs[index], lastRunStatus: status };
				return {
					runsByTrigger: { ...state.runsByTrigger, [triggerId]: next },
				};
			}
			return state;
		});
	},
}));

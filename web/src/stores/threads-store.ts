import { create } from "zustand";
import { Thread } from "@/types/threads";
import { RunTerminalStatus } from "@/types/runs";
import { api } from "@/lib/api/client";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";

interface ThreadsState {
	threads: Thread[];
	fetchThreads: () => Promise<void>;
	addThread: (thread: Thread) => void;
	removeThread: (threadId: string) => void;
	renameThread: (threadId: string, firstMessageContent: string) => void;
	markAgentArchived: (agentId: string) => void;
	/** Stamp a run outcome observed by the active-runs poll (sidebar badge). */
	setLastRunStatus: (threadId: string, status: RunTerminalStatus) => void;
}

export const useThreadsStore = create<ThreadsState>((set) => ({
	threads: [],
	fetchThreads: async () => {
		try {
			const response = await api.get("/threads");
			set({ threads: response.data });
		} catch (error) {
			console.error("Error fetching threads:", error);
		}
	},
	addThread: (thread) => {
		set((state) => ({ threads: [thread, ...state.threads] }));
	},
	removeThread: (threadId) => {
		// A deleted thread is also a deleted trigger firing — keep run
		// history in sync.
		useTriggerRunsStore.getState().removeRun(threadId);
		set((state) => ({
			threads: state.threads.filter((thread) => thread.id !== threadId),
		}));
	},
	renameThread: (threadId, firstMessageContent) => {
		set((state) => ({
			threads: state.threads.map((thread) =>
				thread.id === threadId ? { ...thread, firstMessageContent } : thread,
			),
		}));
	},
	markAgentArchived: (agentId) => {
		set((state) => ({
			threads: state.threads.map((thread) =>
				thread.agentId === agentId
					? { ...thread, agentArchived: true, agentName: null }
					: thread,
			),
		}));
	},
	setLastRunStatus: (threadId, status) => {
		set((state) => {
			const thread = state.threads.find((t) => t.id === threadId);
			if (!thread || thread.lastRunStatus === status) return state;
			return {
				threads: state.threads.map((t) =>
					t.id === threadId ? { ...t, lastRunStatus: status } : t,
				),
			};
		});
	},
}));

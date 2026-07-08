import { create } from "zustand";
import { Thread } from "@/types/threads";
import { Paginated } from "@/types/api";
import { RunTerminalStatus } from "@/types/runs";
import { api } from "@/lib/api/client";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";

const PAGE_SIZE = 30;

interface ThreadsState {
	threads: Thread[];
	/** Server-side total for the current user; drives hasMoreThreads. */
	total: number;
	isLoadingMore: boolean;
	/** Fetch the first page, replacing the current list. */
	fetchThreads: () => Promise<void>;
	/** Append the next page (deduped by id — new threads shift offsets). */
	loadMoreThreads: () => Promise<void>;
	addThread: (thread: Thread) => void;
	removeThread: (threadId: string) => void;
	renameThread: (threadId: string, firstMessageContent: string) => void;
	markAgentArchived: (agentId: string) => void;
	/** Stamp a run outcome observed by the active-runs poll (sidebar badge). */
	setLastRunStatus: (threadId: string, status: RunTerminalStatus) => void;
}

export const useThreadsStore = create<ThreadsState>((set, get) => ({
	threads: [],
	total: 0,
	isLoadingMore: false,
	fetchThreads: async () => {
		try {
			const response = await api.get<Paginated<Thread>>("/threads", {
				params: { limit: PAGE_SIZE, offset: 0 },
			});
			set({ threads: response.data.items, total: response.data.total });
		} catch (error) {
			console.error("Error fetching threads:", error);
		}
	},
	loadMoreThreads: async () => {
		const { threads, total, isLoadingMore } = get();
		if (isLoadingMore || threads.length >= total) return;
		set({ isLoadingMore: true });
		try {
			const response = await api.get<Paginated<Thread>>("/threads", {
				params: { limit: PAGE_SIZE, offset: threads.length },
			});
			set((state) => {
				const seen = new Set(state.threads.map((t) => t.id));
				const fresh = response.data.items.filter((t) => !seen.has(t.id));
				return {
					threads: [...state.threads, ...fresh],
					total: response.data.total,
				};
			});
		} catch (error) {
			console.error("Error loading more threads:", error);
		} finally {
			set({ isLoadingMore: false });
		}
	},
	addThread: (thread) => {
		set((state) => ({
			threads: [thread, ...state.threads],
			total: state.total + 1,
		}));
	},
	removeThread: (threadId) => {
		// A deleted thread is also a deleted trigger firing — keep run
		// history in sync.
		useTriggerRunsStore.getState().removeRun(threadId);
		set((state) => {
			const threads = state.threads.filter(
				(thread) => thread.id !== threadId,
			);
			const removed = state.threads.length - threads.length;
			return { threads, total: Math.max(0, state.total - removed) };
		});
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

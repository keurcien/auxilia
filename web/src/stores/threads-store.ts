import { create } from "zustand";
import { Thread } from "@/types/threads";
import { RunTerminalStatus } from "@/types/runs";
import * as threadsApi from "@/lib/api/resources/threads";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";
import { getWorkspaceGeneration, isCurrentWorkspaceGeneration } from "@/lib/workspace-generation";

const PAGE_SIZE = 30;

interface ThreadsState {
	threads: Thread[];
	/** Server-side total for the current user; drives hasMoreThreads. */
	total: number;
	isLoadingMore: boolean;
	/** Fetch the first page, replacing the current list. */
	fetchThreads: () => Promise<void>;
	refreshThreads: () => Promise<void>;
	/** Merge newly-created first-page threads into the current sidebar list. */
	pollRecentThreads: () => Promise<void>;
	/** Append the next page (deduped by id — new threads shift offsets). */
	loadMoreThreads: () => Promise<void>;
	addThread: (thread: Thread) => void;
	removeThread: (threadId: string) => void;
	removeThreadsForAgent: (agentId: string) => string[];
	renameThread: (threadId: string, firstMessageContent: string) => void;
	setThreadPlacement: (
		threadId: string,
		projectId: string | null,
		folderId: string | null,
	) => Promise<Thread>;
	setThreadCompleted: (threadId: string, completed: boolean) => Promise<Thread>;
	markAgentArchived: (agentId: string) => void;
	markAgentRestored: (agentId: string, agentName: string) => void;
	/** Stamp a run outcome observed by the active-runs poll (sidebar badge). */
	setLastRunStatus: (threadId: string, status: RunTerminalStatus) => void;
}

export const useThreadsStore = create<ThreadsState>((set, get) => ({
	threads: [],
	total: 0,
	isLoadingMore: false,
	fetchThreads: async () => {
		await get().refreshThreads();
	},
	refreshThreads: async () => {
		const generation = getWorkspaceGeneration();
		try {
			const page = await threadsApi.listThreads({ limit: PAGE_SIZE, offset: 0 });
			if (isCurrentWorkspaceGeneration(generation)) {
				set({ threads: page.items, total: page.total });
			}
		} catch (error) {
			console.error("Error fetching threads:", error);
		}
	},
	pollRecentThreads: async () => {
		const generation = getWorkspaceGeneration();
		try {
			const page = await threadsApi.listThreads({ limit: PAGE_SIZE, offset: 0 });
			if (!isCurrentWorkspaceGeneration(generation)) return;
			set((state) => {
				const incoming = new Map(
					page.items.map((thread) => [thread.id, thread]),
				);
				const knownIds = new Set(state.threads.map((thread) => thread.id));
				const newThreads = page.items.filter(
					(thread) => !knownIds.has(thread.id),
				);
				return {
					threads: [
						...newThreads,
						...state.threads.map(
							(thread) => incoming.get(thread.id) ?? thread,
						),
					],
					total: page.total,
				};
			});
		} catch (error) {
			console.error("Error polling recent threads:", error);
		}
	},
	loadMoreThreads: async () => {
		const generation = getWorkspaceGeneration();
		const { threads, total, isLoadingMore } = get();
		if (isLoadingMore || threads.length >= total) return;
		set({ isLoadingMore: true });
		try {
			const page = await threadsApi.listThreads({
				limit: PAGE_SIZE,
				offset: threads.length,
			});
			if (!isCurrentWorkspaceGeneration(generation)) return;
			set((state) => {
				const seen = new Set(state.threads.map((t) => t.id));
				const fresh = page.items.filter((t) => !seen.has(t.id));
				return {
					threads: [...state.threads, ...fresh],
					total: page.total,
				};
			});
		} catch (error) {
			console.error("Error loading more threads:", error);
		} finally {
			if (isCurrentWorkspaceGeneration(generation)) {
				set({ isLoadingMore: false });
			}
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
	removeThreadsForAgent: (agentId) => {
		const threadIds = get()
			.threads.filter((thread) => thread.agentId === agentId)
			.map((thread) => thread.id);
		for (const threadId of threadIds) {
			useTriggerRunsStore.getState().removeRun(threadId);
		}
		set((state) => {
			const threads = state.threads.filter((thread) => thread.agentId !== agentId);
			const removed = state.threads.length - threads.length;
			return { threads, total: Math.max(0, state.total - removed) };
		});
		return threadIds;
	},
	renameThread: (threadId, firstMessageContent) => {
		set((state) => ({
			threads: state.threads.map((thread) =>
				thread.id === threadId ? { ...thread, firstMessageContent } : thread,
			),
		}));
	},
	setThreadPlacement: async (threadId, projectId, folderId) => {
		const previous = get().threads.find((thread) => thread.id === threadId);
		set((state) => ({
			threads: state.threads.map((thread) =>
				thread.id === threadId ? { ...thread, projectId, folderId } : thread,
			),
		}));
		try {
			const updated = await threadsApi.updateThreadPlacement(
				threadId,
				projectId,
				folderId,
			);
			set((state) => ({
				threads: state.threads.map((thread) =>
					thread.id === threadId ? { ...thread, ...updated } : thread,
				),
			}));
			return updated;
		} catch (error) {
			if (previous) {
				set((state) => ({
					threads: state.threads.map((thread) =>
						thread.id === threadId ? previous : thread,
					),
				}));
			}
			throw error;
		}
	},
	setThreadCompleted: async (threadId, completed) => {
		const previous = get().threads.find((thread) => thread.id === threadId);
		const completedAt = completed ? new Date().toISOString() : null;
		set((state) => ({
			threads: state.threads.map((thread) =>
				thread.id === threadId ? { ...thread, completedAt } : thread,
			),
		}));
		try {
			const updated = await threadsApi.updateThreadCompletion(threadId, completed);
			set((state) => ({
				threads: state.threads.map((thread) =>
					thread.id === threadId ? { ...thread, ...updated } : thread,
				),
			}));
			return updated;
		} catch (error) {
			if (previous) {
				set((state) => ({
					threads: state.threads.map((thread) =>
						thread.id === threadId ? previous : thread,
					),
				}));
			}
			throw error;
		}
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
	markAgentRestored: (agentId, agentName) => {
		set((state) => ({
			threads: state.threads.map((thread) =>
				thread.agentId === agentId
					? { ...thread, agentArchived: false, agentName }
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

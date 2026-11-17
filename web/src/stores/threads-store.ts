import { create } from "zustand";
import { Thread } from "@/types/threads";
import { RunTerminalStatus } from "@/types/runs";
import * as threadsApi from "@/lib/api/resources/threads";
import { useProjectsStore } from "@/stores/projects-store";
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
	/** Refresh and reorder the sidebar's first page by latest activity. */
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
	setThreadReadState: (threadId: string, isUnread: boolean) => Promise<void>;
	markAgentArchived: (agentId: string) => void;
	markAgentRestored: (agentId: string, agentName: string) => void;
	/** Stamp a run outcome observed by the active-runs poll (sidebar badge). */
	setLastRunStatus: (threadId: string, status: RunTerminalStatus) => void;
}

// Workspace events arrive in bursts. Concurrent first-page reads can resolve
// out of order, so a response that predates a change would overwrite the one
// that follows it: run them one after another instead.
let firstPageLoad: Promise<void> = Promise.resolve();
const loadFirstPageAfterPrevious = (load: () => Promise<void>) => {
	firstPageLoad = firstPageLoad.then(load, load);
	return firstPageLoad;
};

export const useThreadsStore = create<ThreadsState>((set, get) => ({
	threads: [],
	total: 0,
	isLoadingMore: false,
	fetchThreads: async () => {
		await get().refreshThreads();
	},
	refreshThreads: () =>
		loadFirstPageAfterPrevious(async () => {
			const generation = getWorkspaceGeneration();
			try {
				const page = await threadsApi.listThreads({
					limit: PAGE_SIZE,
					offset: 0,
					order: "activity",
				});
				if (isCurrentWorkspaceGeneration(generation)) {
					set({ threads: page.items, total: page.total });
				}
			} catch (error) {
				console.error("Error fetching threads:", error);
			}
		}),
	pollRecentThreads: () =>
		loadFirstPageAfterPrevious(async () => {
			const generation = getWorkspaceGeneration();
			try {
				const page = await threadsApi.listThreads({
					limit: PAGE_SIZE,
					offset: 0,
					order: "activity",
				});
				if (!isCurrentWorkspaceGeneration(generation)) return;
				set((state) => {
					const refreshedIds = new Set(page.items.map((thread) => thread.id));
					return {
						threads: [
							...page.items,
							...state.threads.filter(
								(thread) => !refreshedIds.has(thread.id),
							),
						],
						total: page.total,
					};
				});
			} catch (error) {
				console.error("Error polling recent threads:", error);
			}
		}),
	loadMoreThreads: async () => {
		const generation = getWorkspaceGeneration();
		const { threads, total, isLoadingMore } = get();
		if (isLoadingMore || threads.length >= total) return;
		set({ isLoadingMore: true });
		try {
			const page = await threadsApi.listThreads({
				limit: PAGE_SIZE,
				offset: threads.length,
				order: "activity",
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
				thread.id === threadId
					? {
							...thread,
							completedAt,
							isUnread: completed ? false : thread.isUnread,
						}
					: thread,
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
	setThreadReadState: async (threadId, isUnread) => {
		const previous = get().threads.find((thread) => thread.id === threadId);
		const projects = useProjectsStore.getState();
		const previousProjectThread = projects.tree
			.flatMap((project) => project.threads)
			.find((thread) => thread.id === threadId);
		set((state) => ({
			threads: state.threads.map((thread) =>
				thread.id === threadId ? { ...thread, isUnread } : thread,
			),
		}));
		projects.setThreadReadState(threadId, isUnread);
		try {
			await threadsApi.updateThreadReadState(threadId, isUnread);
		} catch (error) {
			if (previous) {
				set((state) => ({
					threads: state.threads.map((thread) =>
						thread.id === threadId ? previous : thread,
					),
				}));
			}
			if (previousProjectThread) {
				useProjectsStore
					.getState()
					.setThreadReadState(threadId, previousProjectThread.isUnread);
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

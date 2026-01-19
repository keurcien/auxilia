import { create } from "zustand";
import { Thread } from "@/types/threads";
import { api } from "@/lib/api/client";

interface ThreadsState {
	threads: Thread[];
	fetchThreads: () => Promise<void>;
	addThread: (thread: Thread) => void;
	removeThread: (threadId: string) => void;
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
	addThread: (thread) =>
		set((state) => ({ threads: [thread, ...state.threads] })),
	removeThread: (threadId) =>
		set((state) => ({
			threads: state.threads.filter((thread) => thread.id !== threadId),
		})),
}));

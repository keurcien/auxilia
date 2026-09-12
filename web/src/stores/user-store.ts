import { create } from "zustand";
import * as authApi from "@/lib/api/resources/auth";
import type { CurrentUser } from "@/types/auth";

interface UserStore {
	user: CurrentUser | null;
	isLoading: boolean;
	isInitialized: boolean;
	fetchUser: () => Promise<void>;
	logout: () => Promise<void>;
	clearUser: () => void;
}

export const useUserStore = create<UserStore>((set, get) => ({
	user: null,
	isLoading: false,
	isInitialized: false,

	fetchUser: async () => {
		if (get().isInitialized || get().isLoading) return;

		set({ isLoading: true });
		try {
			const user = await authApi.getCurrentUser();
			set({ user, isInitialized: true });
		} catch {
			set({ user: null, isInitialized: true });
		} finally {
			set({ isLoading: false });
		}
	},

	logout: async () => {
		try {
			await authApi.signOut();
		} finally {
			set({ user: null, isInitialized: false });
			window.location.href = "/auth";
		}
	},

	clearUser: () => {
		set({ user: null, isInitialized: false });
	},
}));

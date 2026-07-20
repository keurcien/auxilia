import { create } from "zustand";
import { api } from "@/lib/api/client";

interface User {
	id: string;
	name: string | null;
	email: string | null;
	role: "member" | "editor" | "admin";
	createdAt: string;
	updatedAt: string;
}

interface UserStore {
	user: User | null;
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
		// isLoading doubles as an in-flight guard: sidebar and pages both call
		// this on mount, and only one /auth/me request should go out.
		if (get().isInitialized || get().isLoading) return;

		set({ isLoading: true });
		try {
			const response = await api.get("/auth/me");
			set({ user: response.data, isInitialized: true });
		} catch {
			set({ user: null, isInitialized: true });
		} finally {
			set({ isLoading: false });
		}
	},

	logout: async () => {
		try {
			await api.post("/auth/signout");
		} finally {
			set({ user: null, isInitialized: false });
			window.location.href = "/auth";
		}
	},

	clearUser: () => {
		set({ user: null, isInitialized: false });
	},
}));

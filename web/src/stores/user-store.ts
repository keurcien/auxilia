import { create } from "zustand";
import * as authApi from "@/lib/api/resources/auth";
import * as usersApi from "@/lib/api/resources/users";
import type { CurrentUser } from "@/types/auth";

interface UserStore {
	user: CurrentUser | null;
	isLoading: boolean;
	isInitialized: boolean;
	notificationsSaving: boolean;
	fetchUser: () => Promise<void>;
	setUser: (user: CurrentUser) => void;
	setNotificationsEnabled: (enabled: boolean) => Promise<void>;
	refreshNotifications: () => Promise<void>;
	logout: () => Promise<void>;
	clearUser: () => void;
}

// Only the latest notification request may write, so a slow response
// cannot overwrite a newer toggle or a newer SSE refresh.
let notificationsRequest = 0;

export const useUserStore = create<UserStore>((set, get) => {
	const applyNotifications = (request: number, enabled: boolean) => {
		if (request !== notificationsRequest) return;
		const user = get().user;
		if (user === null || user.notificationsEnabled === enabled) return;
		set({ user: { ...user, notificationsEnabled: enabled } });
	};

	// Webhook trigger conversations are titled in the owner's timezone, so the
	// server keeps the browser's. A supervising admin's browser is not the user's.
	const syncTimezone = (user: CurrentUser) => {
		const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
		if (!timezone || user.supervision || user.timezone === timezone) return;
		usersApi
			.setTimezone(timezone)
			.then((saved) => {
				const current = get().user;
				if (current?.id === user.id) set({ user: { ...current, timezone: saved } });
			})
			.catch(() => undefined);
	};

	return {
		user: null,
		isLoading: false,
		isInitialized: false,
		notificationsSaving: false,

		fetchUser: async () => {
			if (get().isInitialized || get().isLoading) return;

			set({ isLoading: true });
			try {
				const user = await authApi.getCurrentUser();
				set({ user, isInitialized: true });
				syncTimezone(user);
			} catch {
				set({ user: null, isInitialized: true });
			} finally {
				set({ isLoading: false });
			}
		},

		setUser: (user) => {
			set({ user, isInitialized: true });
			syncTimezone(user);
		},

		setNotificationsEnabled: async (enabled) => {
			const previous = get().user?.notificationsEnabled;
			if (previous === undefined) return;
			const request = ++notificationsRequest;
			set({ notificationsSaving: true });
			applyNotifications(request, enabled);
			try {
				applyNotifications(
					request,
					await usersApi.updateNotificationsEnabled(enabled),
				);
			} catch (error) {
				applyNotifications(request, previous);
				throw error;
			} finally {
				if (request === notificationsRequest) {
					set({ notificationsSaving: false });
				}
			}
		},

		refreshNotifications: async () => {
			if (get().user === null) return;
			const request = ++notificationsRequest;
			try {
				applyNotifications(request, await usersApi.getNotificationsEnabled());
			} finally {
				if (request === notificationsRequest) {
					set({ notificationsSaving: false });
				}
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
	};
});

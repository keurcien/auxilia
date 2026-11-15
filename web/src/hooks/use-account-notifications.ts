"use client";

import { useCallback } from "react";
import { toast } from "sonner";

import { getApiErrorMessage } from "@/lib/api/errors";
import { useUserStore } from "@/stores/user-store";
import { useWebPushStore } from "@/stores/web-push-store";

export function useAccountNotifications() {
	const available = useUserStore((state) => state.user !== null);
	const enabled = useUserStore(
		(state) => state.user?.notificationsEnabled ?? true,
	);
	const saving = useUserStore((state) => state.notificationsSaving);
	const webPushState = useWebPushStore((state) => state.state);

	const setEnabled = useCallback(async (next: boolean) => {
		// Subscribing in the same gesture keeps the browser permission prompt
		// allowed; it is the only way this browser starts receiving them.
		const subscribe =
			next && useWebPushStore.getState().state === "disabled"
				? useWebPushStore.getState().enable()
				: Promise.resolve();
		try {
			await Promise.all([
				useUserStore.getState().setNotificationsEnabled(next),
				subscribe,
			]);
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "Notifications could not be updated."),
			);
		}
	}, []);

	return { available, enabled, saving, webPushState, setEnabled };
}

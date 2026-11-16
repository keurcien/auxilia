"use client";

import { useCallback, useState } from "react";
import { toast } from "sonner";

import { getApiErrorMessage } from "@/lib/api/errors";
import * as threadsApi from "@/lib/api/resources/threads";
import { useUserStore } from "@/stores/user-store";
import { useWebPushStore } from "@/stores/web-push-store";
import type { Thread } from "@/types/threads";
import type { WebPushState } from "@/types/web-push";

export interface ThreadNotifications {
	enabled: boolean;
	saving: boolean;
	webPushState: WebPushState;
	setEnabled: (next: boolean) => Promise<void>;
}

/** One conversation's notification switch; the account setting is only its default. */
export function useThreadNotifications(thread: Thread | null): ThreadNotifications {
	const accountDefault = useUserStore(
		(state) => state.user?.notificationsEnabled ?? true,
	);
	const webPushState = useWebPushStore((state) => state.state);
	const [override, setOverride] = useState<{
		threadId: string;
		enabled: boolean;
	} | null>(null);
	const [saving, setSaving] = useState(false);
	const threadId = thread?.id ?? null;
	const enabled =
		override !== null && override.threadId === threadId
			? override.enabled
			: (thread?.notificationsEnabled ?? accountDefault);

	const setEnabled = useCallback(
		async (next: boolean) => {
			if (threadId === null) return;
			const previous = enabled;
			setOverride({ threadId, enabled: next });
			setSaving(true);
			// Subscribing in the same gesture keeps the browser permission prompt
			// allowed; it is the only way this browser starts receiving them.
			if (next && useWebPushStore.getState().state === "disabled") {
				useWebPushStore
					.getState()
					.enable()
					.catch((error: unknown) => {
						toast.error(
							getApiErrorMessage(
								error,
								"This browser could not be subscribed to notifications.",
							),
						);
					});
			}
			try {
				const updated = await threadsApi.updateThreadNotifications(
					threadId,
					next,
				);
				setOverride({
					threadId,
					enabled: updated.notificationsEnabled ?? next,
				});
			} catch (error) {
				setOverride({ threadId, enabled: previous });
				toast.error(
					getApiErrorMessage(error, "Notifications could not be updated."),
				);
			} finally {
				setSaving(false);
			}
		},
		[enabled, threadId],
	);

	return { enabled, saving, webPushState, setEnabled };
}

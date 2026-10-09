"use client";

import { useEffect } from "react";
import { useThreadsStore } from "@/stores/threads-store";

const RECENT_THREADS_POLL_MS = 5_000;

export function useRecentThreadsPoll(enabled: boolean): void {
	useEffect(() => {
		if (!enabled) return;

		let cancelled = false;
		let timer: ReturnType<typeof setTimeout> | undefined;

		const schedule = () => {
			timer = setTimeout(() => {
				void poll();
			}, RECENT_THREADS_POLL_MS);
		};

		const poll = async () => {
			if (cancelled || document.visibilityState === "hidden") return;
			await useThreadsStore.getState().pollRecentThreads();
			if (!cancelled) schedule();
		};

		const handleVisibility = () => {
			clearTimeout(timer);
			if (document.visibilityState === "visible") {
				void poll();
			}
		};

		schedule();
		document.addEventListener("visibilitychange", handleVisibility);
		return () => {
			cancelled = true;
			clearTimeout(timer);
			document.removeEventListener("visibilitychange", handleVisibility);
		};
	}, [enabled]);
}

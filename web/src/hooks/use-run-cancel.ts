"use client";

import { useCallback, useRef } from "react";

import { api } from "@/lib/api/client";

/**
 * Tracks the most recent `run_id` for a thread (captured from the
 * `X-Run-Id` response header on the streaming POST) and exposes an explicit
 * server-side cancel action.
 *
 * The new backend (PRD §5) keeps a run executing on the worker even when the
 * SSE consumer disconnects. Without an explicit cancel call, hitting the Stop
 * button only tears down the local stream — the agent keeps running and
 * burning tokens. This hook closes that gap.
 *
 * If the user submits a fresh prompt before any header has been observed
 * (e.g. they reload mid-run), `cancel()` falls back to `/runs/active` so we
 * can still cancel a run started in another tab.
 */
export function useRunCancel(threadId: string) {
	const runIdRef = useRef<string | null>(null);

	const captureFetch = useCallback<typeof fetch>(async (input, init) => {
		const res = await fetch(input, init);
		const rid = res.headers.get("X-Run-Id");
		if (rid) runIdRef.current = rid;
		return res;
	}, []);

	const cancel = useCallback(async (): Promise<void> => {
		let rid = runIdRef.current;
		if (!rid) {
			try {
				const res = await api.get(`/threads/${threadId}/runs/active`);
				rid = (res.data?.runId as string | undefined) ?? null;
			} catch {
				return;
			}
		}
		if (!rid) return;
		try {
			await api.post(`/threads/${threadId}/runs/${rid}/cancel`);
		} catch {
			// Server already terminal, or transient network — the next stream
			// event resolves UI state. Don't surface the error.
		}
	}, [threadId]);

	const reset = useCallback(() => {
		runIdRef.current = null;
	}, []);

	return { runIdRef, captureFetch, cancel, reset };
}

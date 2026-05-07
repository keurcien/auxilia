"use client";

import { useCallback, useRef } from "react";

import { API_BASE_URL, api } from "@/lib/api/client";

/**
 * Marker key inside the SDK's submit payload that asks the custom fetch to
 * redirect the request to ``GET /runs/{rid}/stream`` instead of POSTing a
 * fresh run. The chat page sets this on mount when it detects an active run
 * for the thread, so navigating back to a thread mid-stream resumes the live
 * tail instead of just rendering the (stale) checkpoint.
 */
export const REATTACH_RUN_ID_KEY = "__reattach_run_id";

/**
 * Tracks the active ``run_id`` for a thread and exposes the run-control
 * surface the chat page needs:
 *
 * - ``customFetch`` is passed to ``FetchStreamTransport``. It both
 *   (a) captures ``X-Run-Id`` from the streaming POST response so we know
 *   what to cancel later, and (b) redirects to ``GET /runs/{rid}/stream``
 *   when the SDK submits a payload carrying ``__reattach_run_id`` — the only
 *   way to make ``useStream`` consume a run it didn't itself start.
 * - ``cancel`` fires ``POST /runs/{rid}/cancel`` so Stop actually stops the
 *   worker rather than just tearing down the local SSE consumer.
 * - ``fetchActiveRunId`` looks up whether a thread has a run still in
 *   flight; the chat page calls this on mount and triggers reattach.
 */
export function useRunCancel(threadId: string) {
	const runIdRef = useRef<string | null>(null);

	const customFetch = useCallback<typeof fetch>(
		async (input, init) => {
			// Reattach intent: the SDK serialised our magic marker into the body.
			// Redirect to the dedicated GET endpoint and return its SSE stream.
			if (typeof init?.body === "string") {
				try {
					const parsed = JSON.parse(init.body);
					const reattachRunId =
						(parsed?.input?.[REATTACH_RUN_ID_KEY] as string | undefined) ??
						null;
					if (reattachRunId) {
						runIdRef.current = reattachRunId;
						return await fetch(
							`${API_BASE_URL}/threads/${threadId}/runs/${reattachRunId}/stream?last_event_id=0`,
							{
								method: "GET",
								signal: init.signal ?? null,
								headers: { "Cache-Control": "no-cache" },
							},
						);
					}
				} catch {
					// Body wasn't valid JSON; fall through to the normal POST below.
				}
			}

			const res = await fetch(input, init);
			const rid = res.headers.get("X-Run-Id");
			if (rid) runIdRef.current = rid;
			return res;
		},
		[threadId],
	);

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

	const fetchActiveRunId = useCallback(async (): Promise<string | null> => {
		try {
			const res = await api.get(`/threads/${threadId}/runs/active`);
			const runId = (res.data?.runId as string | undefined) ?? null;
			const status = res.data?.status as string | undefined;
			if (!runId) return null;
			// Don't reattach to interrupted/terminal runs — the SDK reads the
			// checkpoint state via initialValues and renders the approval UI from
			// there. Only ``running`` benefits from a live tail.
			if (status !== "running") return null;
			return runId;
		} catch {
			return null;
		}
	}, [threadId]);

	const reset = useCallback(() => {
		runIdRef.current = null;
	}, []);

	return { runIdRef, customFetch, cancel, fetchActiveRunId, reset };
}

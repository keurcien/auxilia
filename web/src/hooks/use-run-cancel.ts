"use client";

import { useCallback, useEffect, useRef } from "react";

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

	// Per-thread AbortController. We can't trust the SDK to abort its in-flight
	// fetch on unmount — its threadId effect has no cleanup, so on page
	// unmount the closure holding the fetch promise keeps the TCP socket open.
	// Each thread switch leaks one fetch; after ~6 switches the browser's
	// per-origin HTTP/1.1 connection limit is hit and *every* request (including
	// sidebar nav clicks) queues forever, looking like a UI freeze.
	const localCtrlRef = useRef<AbortController | null>(null);

	const getLocalSignal = useCallback((): AbortSignal => {
		if (!localCtrlRef.current || localCtrlRef.current.signal.aborted) {
			localCtrlRef.current = new AbortController();
		}
		return localCtrlRef.current.signal;
	}, []);

	useEffect(() => {
		return () => {
			// Fires on threadId change AND on unmount. Releases the browser's
			// connection slot. The worker keeps running server-side because
			// run execution is decoupled from the SSE consumer.
			localCtrlRef.current?.abort();
			localCtrlRef.current = null;
			// Don't leak the previous thread's run id into the new thread's
			// cancel/fetch paths — the new thread will repopulate via the
			// X-Run-Id header or a fresh reattach.
			runIdRef.current = null;
		};
	}, [threadId]);

	const customFetch = useCallback<typeof fetch>(
		async (input, init) => {
			const signal = combineSignals(init?.signal, getLocalSignal());

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
								signal,
								headers: { "Cache-Control": "no-cache" },
							},
						);
					}
				} catch {
					// Body wasn't valid JSON; fall through to the normal POST below.
				}
			}

			const res = await fetch(input, { ...init, signal });
			const rid = res.headers.get("X-Run-Id");
			if (rid) runIdRef.current = rid;
			return res;
		},
		[threadId, getLocalSignal],
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

/**
 * Returns a signal that aborts when *either* input signal aborts. Uses
 * ``AbortSignal.any`` where available (Chrome 116+, Firefox 124+, Safari 17.4+)
 * and falls back to a manual listener otherwise.
 */
function combineSignals(
	external: AbortSignal | undefined | null,
	local: AbortSignal,
): AbortSignal {
	if (!external) return local;
	const AnySignal = (AbortSignal as unknown as {
		any?: (signals: AbortSignal[]) => AbortSignal;
	}).any;
	if (typeof AnySignal === "function") {
		return AnySignal([external, local]);
	}
	const ctrl = new AbortController();
	const trip = () => ctrl.abort();
	if (external.aborted || local.aborted) trip();
	else {
		external.addEventListener("abort", trip, { once: true });
		local.addEventListener("abort", trip, { once: true });
	}
	return ctrl.signal;
}

import { useCallback, useEffect, useRef } from "react";

import { api, API_BASE_URL } from "@/lib/api/client";

/**
 * Marker field on a `submit({ ... })` input that tells {@link useDurableRun}'s
 * custom fetch to reattach to an existing run (GET the replay endpoint) instead
 * of POSTing a new run.
 */
export const REATTACH_RUN_FIELD = "__reattach_run_id";

type DurableRun = {
  /** Pass to `FetchStreamTransport({ fetch })` — captures the run id and
   *  redirects reattach submits to the GET replay stream. */
  customFetch: typeof fetch;
  /** Server-side Stop: cancel the in-flight run (best effort). */
  cancel: () => Promise<void>;
  /** The thread's active run id, or null. Used to reattach on mount. */
  fetchActiveRunId: () => Promise<string | null>;
};

function extractReattachRunId(body: BodyInit | null | undefined): string | null {
  if (typeof body !== "string") return null;
  try {
    const parsed = JSON.parse(body) as { input?: Record<string, unknown> };
    const value = parsed.input?.[REATTACH_RUN_FIELD];
    return typeof value === "string" ? value : null;
  } catch {
    return null;
  }
}

/**
 * Durable-run client glue for a chat thread.
 *
 * The backend's `/runs/stream` returns the run id in an `X-Run-Id` header and
 * keeps the run alive past the request. This hook captures that id (so Stop can
 * cancel server-side), reattaches to an in-flight run by replaying its event log
 * via `GET /runs/{run_id}/stream`, and aborts the in-flight fetch when the
 * thread changes or the page unmounts (the SDK otherwise leaks the connection).
 */
export function useDurableRun(threadId: string): DurableRun {
  const runIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const customFetch = useCallback<typeof fetch>(
    async (input, init) => {
      const controller = new AbortController();
      abortRef.current = controller;
      const signal = init?.signal
        ? AbortSignal.any([init.signal, controller.signal])
        : controller.signal;

      const reattachRunId = extractReattachRunId(init?.body);
      if (reattachRunId) {
        runIdRef.current = reattachRunId;
        const url = `${API_BASE_URL}/threads/${threadId}/runs/${reattachRunId}/stream?last_event_id=0`;
        return fetch(url, { method: "GET", credentials: "include", signal });
      }

      const response = await fetch(input, { ...init, signal });
      const runId = response.headers.get("X-Run-Id");
      if (runId) runIdRef.current = runId;
      return response;
    },
    [threadId],
  );

  const cancel = useCallback(async () => {
    const runId = runIdRef.current;
    if (!runId) return;
    try {
      await api.post(`/threads/${threadId}/runs/${runId}/cancel`);
    } catch {
      // Best effort: the local stream is already stopped; the reaper will
      // recover the run if the cancel POST didn't land.
    }
  }, [threadId]);

  const fetchActiveRunId = useCallback(async () => {
    try {
      const response = await api.get(`/threads/${threadId}/runs/active`);
      const runId = (response.data as { id?: string } | null)?.id;
      return runId ?? null;
    } catch {
      return null;
    }
  }, [threadId]);

  // Abort the in-flight stream fetch on thread switch / unmount.
  useEffect(() => {
    return () => abortRef.current?.abort();
  }, [threadId]);

  return { customFetch, cancel, fetchActiveRunId };
}

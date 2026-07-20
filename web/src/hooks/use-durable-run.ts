import { useCallback, useEffect, useRef } from "react";

import { api, API_BASE_URL } from "@/lib/api/client";
import { useActiveRunsStore } from "@/stores/active-runs-store";

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
    // The marker is set by us (REATTACH_RUN_FIELD) on the submit input. Read it
    // via static access (the key is a constant, not user input — no
    // object-injection vector). NOTE: the literal `__reattach_run_id` here must
    // stay in sync with REATTACH_RUN_FIELD; it's spelled out so the static key
    // satisfies the object-injection lint.
    const parsed = JSON.parse(body) as {
      input?: { __reattach_run_id?: unknown };
    };
    const value = parsed.input?.__reattach_run_id;
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
    async (_input, init) => {
      const controller = new AbortController();
      abortRef.current = controller;
      // Combine the SDK's signal with ours when AbortSignal.any is available;
      // fall back to ours alone on older browsers that lack it.
      const signal =
        init?.signal && typeof AbortSignal.any === "function"
          ? AbortSignal.any([init.signal, controller.signal])
          : controller.signal;

      // Build the target ourselves from the constant, same-origin base and
      // encoded path segments — never forward the SDK's opaque `input` — so no
      // unsanitized value can reach fetch or manipulate the path.
      const thread = encodeURIComponent(threadId);
      // Both paths mean a run is in flight — light the sidebar spinner now
      // instead of waiting for the next active-runs poll.
      useActiveRunsStore.getState().markThreadRunning(threadId);
      const reattachRunId = extractReattachRunId(init?.body);
      if (reattachRunId) {
        runIdRef.current = reattachRunId;
        const url = `${API_BASE_URL}/threads/${thread}/runs/${encodeURIComponent(reattachRunId)}/stream?last_event_id=0`;
        return fetch(url, { method: "GET", credentials: "include", signal });
      }

      const url = `${API_BASE_URL}/threads/${thread}/runs/stream`;
      const response = await fetch(url, { ...init, signal });
      if (response.status === 409) {
        // The pre-stream model gate: surface its human-readable reason as the
        // stream error instead of the SDK's generic failure message. Covers
        // the race where an admin disables the model while this page is open
        // (on load the thread GET's modelAvailable flag hides the composer).
        const body = (await response
          .clone()
          .json()
          .catch(() => null)) as { error?: string; detail?: string } | null;
        if (body?.error === "model_unavailable") {
          throw new Error(
            body.detail ??
              "This conversation's model is no longer available in this workspace.",
          );
        }
      }
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
      await api.post(
        `/threads/${encodeURIComponent(threadId)}/runs/${encodeURIComponent(runId)}/cancel`,
      );
    } catch {
      // Best effort: the local stream is already stopped; the reaper will
      // recover the run if the cancel POST didn't land.
    }
  }, [threadId]);

  const fetchActiveRunId = useCallback(async () => {
    try {
      const response = await api.get(
        `/threads/${encodeURIComponent(threadId)}/runs/active`,
      );
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

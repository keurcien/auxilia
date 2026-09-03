import { useCallback, useEffect, useMemo, useRef } from "react";

import { useActiveRunsStore } from "@/stores/active-runs-store";

export type ProtocolFetchHandlers = {
  /** The pre-run model gate 409'd: an admin disabled the thread's model. */
  onModelUnavailable?: () => void;
  /** The addressed approval was already handled from another surface. */
  onStaleInterrupt?: () => void;
};

/**
 * Fetch wrapper for the Agent Streaming Protocol transport
 * (`useStream({ apiUrl, fetch })`): same-origin guard, active-run bookkeeping
 * around `run.start`, and translation of the backend's pre-run 409 gates into
 * domain side effects (lock the composer, reload on a stale approval). The
 * stream stack only exposes command failures as an opaque `stream.error`, so
 * this is where the machine-readable body is still readable; the named error
 * still propagates so the SDK records the failure.
 */
export function useProtocolFetch(
  threadId: string,
  handlers: ProtocolFetchHandlers = {},
): typeof fetch {
  const markRunning = useCallback(() => {
    // Light the sidebar spinner as soon as a run.start command goes out,
    // instead of waiting for the next active-runs poll.
    useActiveRunsStore.getState().markThreadRunning(threadId);
  }, [threadId]);

  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  });

  return useMemo<typeof fetch>(() => {
    return async (input, init) => {
      // Defense-in-depth: this fetch attaches session credentials, so it
      // must only ever reach the same-origin API proxy the SDK was
      // configured with — never a cross-origin URL. Resolve the URL the way
      // Fetch would (catching protocol-relative `//host` and backslash
      // variants a prefix check misses) and compare real origins, then
      // rebuild the request target from the validated parts so nothing
      // un-parsed reaches fetch. Fail closed when no origin exists (SSR
      // never issues these requests).
      const raw =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      const origin = typeof window === "undefined" ? "" : window.location.origin;
      const parsed = origin ? new URL(raw, origin) : null;
      if (parsed == null || parsed.origin !== origin) {
        throw new Error(`Blocked non-same-origin request: ${raw}`);
      }
      const url = `${origin}${parsed.pathname}${parsed.search}`;
      // Only a run.start command lights the sidebar spinner — parse the
      // envelope's method rather than substring-matching the body (a
      // resume decision could legitimately contain the literal string).
      let method: unknown;
      if (typeof init?.body === "string") {
        try {
          method = (JSON.parse(init.body) as { method?: unknown }).method;
        } catch {
          // Non-JSON bodies (the SSE subscribe filter) are never commands.
        }
      }
      if (method === "run.start") {
        markRunning();
      }
      // The taint scanner can't see the sanitizer above: `url` is rebuilt
      // from the page origin plus the parsed-and-validated path of a request
      // the SDK constructed from our own constant apiUrl — it is origin-
      // pinned by construction and cannot reach another host.
      // nosemgrep
      const response = await fetch(url, { credentials: "include", ...init });
      if (method === "run.start" && !response.ok) {
        // The optimistic spinner must not outlive a rejected launch — ask
        // the active-runs poller to reconcile with server truth now.
        useActiveRunsStore.getState().requestPoll();
      }
      if (response.status === 409) {
        const body = (await response
          .clone()
          .json()
          .catch(() => null)) as { error?: string; detail?: string } | null;
        if (body?.error === "model_unavailable") {
          handlersRef.current.onModelUnavailable?.();
          const err = new Error(
            body.detail ??
              "This conversation's model is no longer available in this workspace.",
          );
          err.name = "ModelUnavailableError";
          throw err;
        }
        if (body?.error === "stale_interrupt") {
          handlersRef.current.onStaleInterrupt?.();
          const err = new Error(
            body.detail ?? "This approval was already handled elsewhere.",
          );
          err.name = "StaleInterruptError";
          throw err;
        }
      }
      return response;
    };
  }, [markRunning]);
}

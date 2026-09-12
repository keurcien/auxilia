import { useEffect, useMemo, useRef } from "react";

import {
  decodeProtocolRejection,
  protocolCommandMethod,
  protocolFetch,
  protocolRejectionError,
} from "@/lib/api/protocol";
import { useActiveRunsStore } from "@/stores/active-runs-store";

export type ProtocolFetchHandlers = {
  /** The pre-run model gate 409'd: an admin disabled the thread's model. */
  onModelUnavailable?: () => void;
  /** The addressed approval was already handled from another surface. */
  onStaleInterrupt?: () => void;
};

/**
 * The `fetch` handed to `useStream({ apiUrl, fetch })`: `protocolFetch` plus
 * active-run bookkeeping around `run.start`, and the backend's pre-run 409
 * gates decoded into domain side effects (lock the composer, reload on a
 * stale approval). The stream stack only exposes command failures as an
 * opaque `stream.error`, so this is where the machine-readable body is still
 * readable; the named error still propagates so the SDK records the failure.
 */
export function useProtocolFetch(
  threadId: string,
  handlers: ProtocolFetchHandlers = {},
): typeof fetch {
  const handlersRef = useRef(handlers);
  useEffect(() => {
    handlersRef.current = handlers;
  });

  return useMemo<typeof fetch>(() => {
    return async (input, init) => {
      const method = protocolCommandMethod(init);
      if (method === "run.start") {
        useActiveRunsStore.getState().markThreadRunning(threadId);
      }
      const response = await protocolFetch(input, init);
      if (method === "run.start" && !response.ok) {
        useActiveRunsStore.getState().requestPoll();
      }
      if (response.status === 409) {
        const body: unknown = await response
          .clone()
          .json()
          .catch(() => null);
        const rejection = decodeProtocolRejection(response.status, body);
        if (rejection) {
          if (rejection.kind === "model_unavailable") {
            handlersRef.current.onModelUnavailable?.();
          } else {
            handlersRef.current.onStaleInterrupt?.();
          }
          throw protocolRejectionError(rejection);
        }
      }
      return response;
    };
  }, [threadId]);
}

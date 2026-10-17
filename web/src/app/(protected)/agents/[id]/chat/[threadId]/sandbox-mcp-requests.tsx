"use client";

import { toHttpUrl } from "@/lib/urls/http";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { getApiErrorMessage } from "@/lib/api/errors";
import { decideSandboxMcp, pendingSandboxMcp, type SandboxMcpRequest } from "@/lib/api/resources/sandbox-mcp";

/** Independent of execute completion: a script can wait while the user connects. */
export function SandboxMcpRequests({ threadId, enabled }: { threadId: string; enabled: boolean }) {
  const answered = useRef(new Set<string>());
  const [requests, setRequests] = useState<SandboxMcpRequest[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const pending = await pendingSandboxMcp(threadId, controller.signal);
        if (!controller.signal.aborted) {
          setRequests(pending.filter(item => !answered.current.has(item.phase)));
          setPollError(null);
        }
      } catch (error) {
        if (!controller.signal.aborted) setPollError(getApiErrorMessage(error, "Could not check pending tool requests."));
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(() => { void poll(); }, 5000);
      }
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [threadId, enabled]);

  async function decide(request: SandboxMcpRequest, decision: "approve" | "reject") {
    setBusy(request.phase);
    setError(null);
    try {
      await decideSandboxMcp(threadId, request, decision);
      answered.current.add(request.phase);
      setRequests(current => current.filter(item => item.phase !== request.phase));
    } catch (error) {
      setError(getApiErrorMessage(error, "Could not submit your decision."));
    } finally {
      setBusy(null);
    }
  }

  if (!enabled) return null;
  return <div className="space-y-3" aria-live="polite">
    {requests.map(request => {
      const auth = request.status === "oauth_required";
      const authUrl = toHttpUrl(request.authUrl);
      return <div key={request.phase} className="rounded-lg border p-4 space-y-3">
        <p className="text-sm font-medium">{auth ? "Connection needed" : "Approval needed"}: {request.tool}</p>
        {!auth && <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(request.arguments, null, 2)}</pre>}
        {auth && <p className="text-sm text-muted-foreground">Connect in the new window. Your task will continue automatically after authorization.</p>}
        <div className="flex gap-2">
          {auth ? <Button size="sm" disabled={!authUrl} onClick={() => {
            if (authUrl) window.open(authUrl, "_blank", "noopener,noreferrer,width=600,height=700");
          }}>Connect</Button> : <Button size="sm" disabled={busy !== null} onClick={() => { void decide(request, "approve"); }}>Approve</Button>}
          <Button size="sm" variant="outline" disabled={busy !== null} onClick={() => { void decide(request, "reject"); }}>{auth ? "Cancel" : "Reject"}</Button>
        </div>
      </div>;
    })}
    {(error || pollError) && <p role="alert" className="text-sm text-destructive">{error || pollError}</p>}
  </div>;
}

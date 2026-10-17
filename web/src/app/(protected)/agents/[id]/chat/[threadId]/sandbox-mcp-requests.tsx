"use client";

import type { Interrupt } from "@langchain/langgraph-sdk";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { HitlResponse } from "@/hooks/use-hitl-approvals";
import { toHttpUrl } from "@/lib/urls/http";

/** The bridge half of an `input.requested` payload — `request_payload` in
 *  `app/runtime/sandbox_mcp/service.py`. */
type SandboxMcpPayload = {
  operation_id: string;
  agent: string;
  status: "approval_required" | "oauth_required";
  auth_url?: string | null;
};

export type SandboxMcpRequest = SandboxMcpPayload & {
  interruptId: string;
  tool: string;
  arguments: unknown;
};

/** A sandbox script's MCP call waiting on the user, or null for any other
 *  interrupt (the graph's approvals belong to the tool steps). */
export function sandboxMcpRequest(interrupt: Interrupt): SandboxMcpRequest | null {
  const value = interrupt.value as {
    sandbox_mcp?: SandboxMcpPayload;
    action_requests?: { name?: string; args?: unknown }[];
  } | null;
  const bridge = value?.sandbox_mcp;
  if (!bridge || typeof interrupt.id !== "string") return null;
  const [request] = value.action_requests ?? [];
  return { ...bridge, interruptId: interrupt.id, tool: request?.name ?? "tool", arguments: request?.args ?? {} };
}

/**
 * Bridge requests ride `stream.interrupts` like every pending decision and are
 * answered through the same `input.respond`; only the card differs, because
 * the waiting call is not a step of the transcript (the running step is the
 * script's `execute`).
 */
export function SandboxMcpRequests({ interrupts, respond, enabled }: {
  interrupts: readonly Interrupt[];
  respond: (response: HitlResponse, interruptId: string | null) => void;
  enabled: boolean;
}) {
  const [answered, setAnswered] = useState<ReadonlySet<string>>(() => new Set());
  if (!enabled) return null;
  const requests = interrupts.map(sandboxMcpRequest).filter((r): r is SandboxMcpRequest => r != null && !answered.has(r.interruptId));
  if (requests.length === 0) return null;

  function decide(request: SandboxMcpRequest, type: "approve" | "reject") {
    setAnswered(current => new Set(current).add(request.interruptId));
    respond({ decisions: [{ tool_call_id: request.operation_id, type }] }, request.interruptId);
  }

  // shortcut: a request the worker resolves on its own (the OAuth callback
  // landed) stays on screen until the run ends or the page rehydrates — the
  // protocol has no "input resolved" event. Upgrade when one exists.
  return <div className="space-y-3" aria-live="polite">
    {requests.map(request => {
      const auth = request.status === "oauth_required";
      const authUrl = toHttpUrl(request.auth_url);
      return <div key={request.interruptId} className="rounded-lg border p-4 space-y-3">
        <p className="text-sm font-medium">{auth ? "Connection needed" : "Approval needed"}: {request.tool}</p>
        {!auth && <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-xs">{JSON.stringify(request.arguments, null, 2)}</pre>}
        {auth && <p className="text-sm text-muted-foreground">Connect in the new window. Your task will continue automatically after authorization.</p>}
        <div className="flex gap-2">
          {auth ? <Button size="sm" disabled={!authUrl} onClick={() => {
            if (authUrl) window.open(authUrl, "_blank", "noopener,noreferrer,width=600,height=700");
          }}>Connect</Button> : <Button size="sm" onClick={() => { decide(request, "approve"); }}>Approve</Button>}
          <Button size="sm" variant="outline" onClick={() => { decide(request, "reject"); }}>{auth ? "Cancel" : "Reject"}</Button>
        </div>
      </div>;
    })}
  </div>;
}

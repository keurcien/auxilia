import type {
  AIMessage,
  BaseMessage,
  ToolCall,
  ToolMessage,
} from "@langchain/core/messages";
import { isAIMessage, isToolMessage } from "@langchain/core/messages";
import type { AssembledToolCall, ToolCallStatus } from "@langchain/react";
import { parseToolPayload } from "@langchain/langgraph-sdk/stream";
import { extractToolErrorText } from "@/lib/utils/tool-content";

/** Where an MCP-app tool renders: the app resource and the server that owns it. */
export type McpAppToolInfo = {
  resourceUri: string;
  serverId: string;
};

export type ToolCallView = {
  /** Stable key: the call's own id, or `<message id>-tc-<index>` when the
   *  provider persisted none. */
  id: string;
  /** The call's own id, when it has one — the HITL resume is keyed by it. */
  callId: string | undefined;
  name: string;
  args: Record<string, unknown> | undefined;
  /** Id of the AI message that made the call (chains group by it). */
  messageId: string | undefined;
  /** The `tools`-channel vocabulary: running → finished | error. */
  status: ToolCallStatus;
  /** Parsed tool result, once finished. */
  output: unknown;
  /** Error text, once failed. */
  error: string | undefined;
  /** MCP artifact (structured content, app resource URI), when returned. */
  artifact: Record<string, unknown> | undefined;
  /** Id of the ToolMessage holding the result — the key for fetching it whole. */
  resultMessageId?: string;
  /** Set when the snapshot carries only a preview of the result: the full
   *  length in characters (backend `serialize_message_preview`). */
  truncatedChars?: number;
};

/**
 * Pair every AI tool call with its ToolMessage, then overlay the live handle
 * from the `tools` channel.
 *
 * The overlay is needed live only: the SDK assembles a streamed tool-role
 * message as `ToolMessage({id, content, tool_call_id})` — no `status`, no
 * `artifact` — while hydrated messages carry both. Root `stream.toolCalls`
 * is not seeded from the checkpoint on refresh, so the messages stay the
 * durable view and the handles decorate it.
 */
export function pairToolCalls(
  messages: readonly BaseMessage[],
  live: readonly AssembledToolCall[] = [],
): ToolCallView[] {
  const results = new Map<string, ToolMessage>();
  for (const m of messages) {
    if (isToolMessage(m) && m.tool_call_id) results.set(m.tool_call_id, m);
  }
  const handles = new Map(live.map((tc) => [tc.id, tc]));

  const out: ToolCallView[] = [];
  for (const m of messages) {
    if (!isAIMessage(m)) continue;
    (m.tool_calls ?? []).forEach((call, index) => {
      if (!call.name) return;
      const id = call.id || `${m.id}-tc-${index}`;
      out.push(toView(id, call, m, results.get(id), handles.get(id)));
    });
  }
  return out;
}

function toView(
  id: string,
  call: ToolCall,
  message: AIMessage,
  result: ToolMessage | undefined,
  handle: AssembledToolCall | undefined,
): ToolCallView {
  const status: ToolCallStatus =
    handle?.status ??
    (result ? (result.status === "error" ? "error" : "finished") : "running");
  // The backend wraps an MCP artifact inside `tool-finished.output` as
  // `{content, artifact}` because the SDK's assembler drops extension fields.
  const wrapped =
    handle?.output != null &&
    typeof handle.output === "object" &&
    "artifact" in handle.output
      ? (handle.output as { content?: unknown; artifact?: unknown })
      : undefined;
  const content = result?.content ?? wrapped?.content ?? handle?.output;
  const truncated = (
    result?.additional_kwargs as { truncated?: { chars?: unknown } } | undefined
  )?.truncated;
  return {
    id,
    callId: call.id || undefined,
    name: call.name,
    args: call.args as Record<string, unknown> | undefined,
    messageId: message.id,
    status,
    output:
      status === "finished"
        ? typeof content === "string"
          ? parseToolPayload(content)
          : content
        : undefined,
    error:
      status === "error"
        ? result
          ? extractToolErrorText(result.content)
          : (handle?.error ?? "Tool execution failed")
        : undefined,
    artifact: (result?.artifact ?? wrapped?.artifact) as
      | Record<string, unknown>
      | undefined,
    resultMessageId: result?.id,
    truncatedChars:
      typeof truncated?.chars === "number" ? truncated.chars : undefined,
  };
}

export type ToolStepState =
  | "done"
  | "error"
  | "rejected"
  | "awaiting-approval"
  | "running";

const REJECTION_NOTICE = /^User rejected the tool call\b/;

export function getToolStepState(
  tc: ToolCallView,
  isInterrupted = false,
  hitlToolNames: ReadonlySet<string> | null = null,
): ToolStepState {
  if (tc.status === "finished") return "done";
  if (tc.status === "error") {
    return REJECTION_NOTICE.test(tc.error ?? "") ? "rejected" : "error";
  }
  if (isInterrupted && (!hitlToolNames || hitlToolNames.has(tc.name))) {
    return "awaiting-approval";
  }
  return "running";
}

// ---------------------------------------------------------------------------
// Interrupts — root vs. subagent
// ---------------------------------------------------------------------------

/** MCP app metadata the backend stamps into the artifact
 *  (`app/mcp/client/tools.py`, snake_case on the wire). */
export function getMcpAppInfo(tc: ToolCallView): McpAppToolInfo | null {
  const resourceUri = tc.artifact?.mcp_app_resource_uri as string | undefined;
  const serverId = tc.artifact?.mcp_server_id as string | undefined;
  return resourceUri && serverId ? { resourceUri, serverId } : null;
}

export function getStructuredContent(
  tc: ToolCallView,
): Record<string, unknown> | undefined {
  const sc = tc.artifact?.structuredContent ?? tc.artifact?.structured_content;
  return sc && typeof sc === "object" ? (sc as Record<string, unknown>) : undefined;
}


// ---------------------------------------------------------------------------
// Chains
// ---------------------------------------------------------------------------

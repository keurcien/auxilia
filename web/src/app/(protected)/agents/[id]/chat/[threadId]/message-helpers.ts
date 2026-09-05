/**
 * Pure views over the `@langchain/react` stream: the message log is the one
 * source of truth (`stream.messages` / `useMessages(stream, subagent)`), and
 * everything the conversation renders — tool cards, chains, attachments,
 * reasoning — is derived from it here. The `tools` channel (`stream.toolCalls`
 * / `useToolCalls`) only overlays what a live ToolMessage cannot carry yet:
 * status, error text and the MCP artifact.
 */

import type {
  AIMessage,
  BaseMessage,
  ToolCall,
  ToolMessage,
} from "@langchain/core/messages";
import {
  isAIMessage,
  isHumanMessage,
  isToolMessage,
} from "@langchain/core/messages";
import type { AssembledToolCall, ToolCallStatus } from "@langchain/react";
import type { Interrupt } from "@langchain/langgraph-sdk";
import { parseToolPayload } from "@langchain/langgraph-sdk/stream";
import type { AttachmentData } from "@/components/ai-elements/attachments";
import { extractToolErrorText } from "@/lib/utils/tool-content";
import type { McpAppToolInfo } from "../components/mcp-app-widget";

// ---------------------------------------------------------------------------
// Message content
// ---------------------------------------------------------------------------

/** Reasoning text: v1 `reasoning` blocks, or DeepSeek's `reasoning_content`
 *  on checkpoints written before the v3 protocol. */
export function getReasoning(message: BaseMessage): string | null {
  const blocks = message.contentBlocks
    .filter((b) => b.type === "reasoning")
    .map((b) => (b as { reasoning?: string }).reasoning ?? "");
  if (blocks.length > 0) return blocks.join("\n");
  const legacy = message.additional_kwargs?.reasoning_content;
  return typeof legacy === "string" && legacy ? legacy : null;
}

/** Attachments of a human turn — the `image_url` / `file` blocks the composer
 *  submits (see `handleSubmit` on the chat page). */
export function getFileAttachments(message: BaseMessage): AttachmentData[] {
  if (!Array.isArray(message.content)) return [];
  const attachments: AttachmentData[] = [];
  message.content.forEach((block, idx) => {
    const b = block as Record<string, unknown>;
    if (b.type === "image_url") {
      const image = b.image_url;
      const url =
        typeof image === "string"
          ? image
          : ((image as { url?: string } | undefined)?.url ?? "");
      attachments.push({
        id: `${message.id}-file-${idx}`,
        type: "file",
        url:
          url.startsWith("data:") || /^https?:\/\//.test(url)
            ? url
            : `data:image/jpeg;base64,${url}`,
        filename: "Image.jpg",
        mediaType: "image/jpeg",
      });
    } else if (b.type === "file") {
      const mediaType =
        (b.mime_type as string | undefined) ?? "application/octet-stream";
      attachments.push({
        id: `${message.id}-file-${idx}`,
        type: "file",
        url: `data:${mediaType};base64,${(b.base64 as string | undefined) ?? ""}`,
        filename: (b.filename as string | undefined) ?? "file",
        mediaType,
      });
    }
  });
  return attachments;
}

// ---------------------------------------------------------------------------
// Tool identity
// ---------------------------------------------------------------------------

/** How MCP tool names are namespaced on the backend: `<server>_<tool>`. */
export const sanitizeToolIdentifier = (value: string): string => {
  const sanitized = value
    .replace(/[^a-zA-Z0-9_-]/g, "_")
    .replace(/^_+|_+$/g, "");
  return sanitized || "tool";
};

/** Split `<server>_<tool>` back apart. `knownServerNames` must be sorted
 *  longest-first so `google_sheets_read` is not claimed by `google`. */
export const getToolMetadata = (
  toolName: string,
  knownServerNames: readonly string[],
) => {
  for (const serverName of knownServerNames) {
    for (const alias of [serverName, sanitizeToolIdentifier(serverName)]) {
      if (toolName === alias || toolName.startsWith(`${alias}_`)) {
        const suffix = toolName.slice(alias.length);
        const name = suffix.startsWith("_") ? suffix.slice(1) : suffix;
        return { serverName, toolName: name || toolName };
      }
    }
  }
  const separatorIndex = toolName.indexOf("_");
  if (separatorIndex === -1) return { serverName: toolName, toolName };
  return {
    serverName: toolName.slice(0, separatorIndex),
    toolName: toolName.slice(separatorIndex + 1),
  };
};

// ---------------------------------------------------------------------------
// Tool calls
// ---------------------------------------------------------------------------

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

/** `stream.interrupts` mirrors every namespace's pending interrupt; the root
 *  one drives the root chain's approval UI, the nested ones belong to the
 *  subagent cards (`findSubagentInterrupt`). */
export function splitInterrupts(interrupts: readonly Interrupt[]): {
  root: Interrupt | null;
  nested: Interrupt[];
} {
  let root: Interrupt | null = null;
  const nested: Interrupt[] = [];
  for (const interrupt of interrupts) {
    if (isRootNamespace(interrupt.namespace)) root ??= interrupt;
    else nested.push(interrupt);
  }
  return { root, nested };
}

const isRootNamespace = (namespace: readonly string[] | undefined) =>
  namespace == null || namespace.length === 0;

export const sameNamespace = (
  a: readonly string[] | undefined,
  b: readonly string[],
) => a != null && a.length === b.length && a.every((seg, i) => seg === b[i]);

/**
 * The pending interrupt raised inside one subagent, if any.
 *
 * Live, the backend stamps the subagent's checkpoint namespace
 * (`tools:<pregel task id>`) on `input.requested`, and the SDK binds the same
 * namespace onto the discovery snapshot — an exact match. After a reload the
 * SDK rebuilds snapshots from history with a `tools:<tool_call_id>` namespace
 * instead, so fall back to content: the interrupt's `action_requests` must
 * all correspond to a still-pending call in this card (by name, and by args
 * when both sides have them).
 */
export function findSubagentInterrupt(
  nested: readonly Interrupt[],
  subagent: { namespace: readonly string[] },
  toolCalls: readonly ToolCallView[],
): Interrupt | null {
  const exact = nested.find((i) => sameNamespace(i.namespace, subagent.namespace));
  if (exact) return exact;
  const pending = toolCalls.filter((tc) => tc.status === "running");
  if (pending.length === 0) return null;
  return (
    nested.find((interrupt) => {
      const requests = actionRequests(interrupt.value);
      return (
        requests != null &&
        requests.length > 0 &&
        requests.every((r) =>
          pending.some(
            (tc) =>
              tc.name === r.name &&
              (r.args == null || tc.args == null || sameArgs(tc.args, r.args)),
          ),
        )
      );
    }) ?? null
  );
}

type ActionRequest = { name: string; args?: Record<string, unknown> };

function actionRequests(value: unknown): ActionRequest[] | null {
  if (!value || typeof value !== "object") return null;
  const requests = (value as { action_requests?: unknown }).action_requests;
  if (!Array.isArray(requests)) return null;
  return requests.filter(
    (r): r is ActionRequest =>
      r != null && typeof r === "object" && typeof (r as { name?: unknown }).name === "string",
  );
}

const sameArgs = (a: Record<string, unknown>, b: Record<string, unknown>) => {
  try {
    return JSON.stringify(a, Object.keys(a).sort()) === JSON.stringify(b, Object.keys(b).sort());
  } catch {
    return false;
  }
};

/** The HITL middleware only hangs the tool calls named in the interrupt's
 *  `action_requests`; sibling calls in the same turn run on resume. */
export function extractHitlToolNames(value: unknown): Set<string> | null {
  if (!value || typeof value !== "object") return null;
  const requests = (value as { action_requests?: unknown }).action_requests;
  if (!Array.isArray(requests)) return null;
  return new Set(
    requests
      .map((r: { name?: unknown } | null) => r?.name)
      .filter((n): n is string => typeof n === "string"),
  );
}

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

export type ChainStepData =
  | { kind: "reasoning"; id: string; messageId: string; text: string }
  | { kind: "tool"; id: string; tc: ToolCallView };

/**
 * Group a turn's work into chains of steps: each AI message's reasoning and
 * tool calls, in order. Consecutive AI messages without text extend one chain,
 * owned by the first of them; an AI message with text closes the chain (its
 * own reasoning still lands in it, above the text), a human turn resets it.
 * Returns `owner message id → steps`.
 */
export function groupChains(
  messages: readonly BaseMessage[],
  toolCalls: readonly ToolCallView[],
): Map<string, ChainStepData[]> {
  const callsByMessage = new Map<string, ToolCallView[]>();
  for (const tc of toolCalls) {
    if (!tc.messageId) continue;
    const list = callsByMessage.get(tc.messageId);
    if (list) list.push(tc);
    else callsByMessage.set(tc.messageId, [tc]);
  }

  const chains = new Map<string, ChainStepData[]>();
  let owner: string | null = null;
  for (const m of messages) {
    if (isHumanMessage(m)) {
      owner = null;
      continue;
    }
    if (!isAIMessage(m) || !m.id) continue;
    const hasText = m.text.trim().length > 0;
    const reasoning = getReasoning(m);
    const steps: ChainStepData[] = [
      ...(reasoning
        ? [{ kind: "reasoning" as const, id: `${m.id}-reasoning`, messageId: m.id, text: reasoning }]
        : []),
      ...(callsByMessage.get(m.id) ?? []).map((tc) => ({ kind: "tool" as const, id: tc.id, tc })),
    ];
    if (steps.length > 0) {
      if (owner == null) {
        owner = m.id;
        chains.set(m.id, steps);
      } else {
        chains.get(owner)?.push(...steps);
      }
    }
    if (hasText) owner = null;
  }
  return chains;
}

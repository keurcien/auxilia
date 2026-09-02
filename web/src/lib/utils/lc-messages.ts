// ---------------------------------------------------------------------------
// LangChain message dicts — the plain shape the rendering layer consumes —
// and the adapter from `@langchain/core` BaseMessage class instances (what
// the protocol stream stack yields) back to that shape. Shared between the
// chat page helpers and the subagent components, so it lives in lib/.
// ---------------------------------------------------------------------------

import type { BaseMessage } from "@langchain/core/messages";

export type LCToolCallEntry = {
  name: string;
  args: Record<string, unknown>;
  id?: string;
};

export type LCMessage = {
  type: string;
  content: string | Array<Record<string, unknown>>;
  id?: string;
  name?: string;
  // snake_case (from stream / raw API)
  tool_calls?: LCToolCallEntry[];
  tool_call_id?: string;
  // camelCase (after Axios interceptor)
  toolCalls?: LCToolCallEntry[];
  toolCallId?: string;
  additionalKwargs?: Record<string, unknown>;
  status?: string;
  additional_kwargs?: Record<string, unknown>;
  response_metadata?: Record<string, unknown>;
  artifact?: Record<string, unknown>;
  [key: string]: unknown;
};

// Per-instance cache: the stream store reuses message instances between
// flushes for untouched messages, so mapping is O(changed), not O(all).
const lcMessageCache = new WeakMap<BaseMessage, LCMessage>();

export function baseMessageToLC(message: BaseMessage): LCMessage {
  const cached = lcMessageCache.get(message);
  if (cached) return cached;
  // BaseMessage subclasses carry role-specific fields (tool_calls,
  // tool_call_id, status, artifact) not present on the base type.
  const m = message as unknown as Record<string, unknown>;
  const out: LCMessage = {
    type: message.getType(),
    content: message.content as LCMessage["content"],
    id: message.id,
    name: message.name,
  };
  if (Array.isArray(m.tool_calls) && m.tool_calls.length > 0) {
    out.tool_calls = m.tool_calls as LCToolCallEntry[];
  }
  if (typeof m.tool_call_id === "string") out.tool_call_id = m.tool_call_id;
  if (typeof m.status === "string") out.status = m.status;
  if (m.artifact != null && typeof m.artifact === "object") {
    out.artifact = m.artifact as Record<string, unknown>;
  }
  if (m.additional_kwargs != null && typeof m.additional_kwargs === "object") {
    out.additional_kwargs = m.additional_kwargs as Record<string, unknown>;
  }
  if (m.response_metadata != null && typeof m.response_metadata === "object") {
    out.response_metadata = m.response_metadata as Record<string, unknown>;
  }
  lcMessageCache.set(message, out);
  return out;
}

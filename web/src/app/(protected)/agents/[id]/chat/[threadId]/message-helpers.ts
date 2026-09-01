// ---------------------------------------------------------------------------
// Pure helpers shared by the chat page and its conversation body: extracting
// content from LangChain message dicts, pairing tool calls with results, and
// normalizing snake_case/camelCase shapes. No React, no state — everything
// here is identity-stable so memoized consumers can rely on their inputs.
// ---------------------------------------------------------------------------

import type { SubagentStreamInterface } from "@langchain/langgraph-sdk/ui";
import type { AttachmentData } from "@/components/ai-elements/attachments";
import type { McpAppToolInfo } from "../components/mcp-app-widget";

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

export function getTextContent(message: LCMessage): string {
  if (typeof message.content === "string") return message.content;
  if (Array.isArray(message.content)) {
    return message.content
      .filter((c) => c.type === "text")
      .map((c) => c.text as string)
      .join("");
  }
  return "";
}

export function getReasoningContent(message: LCMessage): string | null {
  // Anthropic: `thinking` blocks in content.
  if (Array.isArray(message.content)) {
    const thinking = message.content.filter((c) => c.type === "thinking");
    if (thinking.length > 0) {
      return thinking.map((c) => (c.thinking as string) || "").join("\n");
    }
  }
  // DeepSeek: reasoning lives in additional_kwargs.reasoning_content, not in
  // content. Streamed messages keep snake_case (SSE bypasses the Axios
  // interceptor); history loaded via GET /threads/{id} is camelCased.
  const kwargs = message.additional_kwargs ?? message.additionalKwargs;
  const reasoning = kwargs?.reasoning_content ?? kwargs?.reasoningContent;
  return typeof reasoning === "string" && reasoning ? reasoning : null;
}

export function getFileAttachments(message: LCMessage): AttachmentData[] {
  if (!Array.isArray(message.content)) return [];
  const attachments: AttachmentData[] = [];
  let idx = 0;

  for (const block of message.content) {
    // Image blocks: "image_url" (snake_case from stream) or "imageUrl" (camelCase from Axios)
    if (block.type === "image_url" || block.type === "imageUrl") {
      const imgField = block.image_url ?? block.imageUrl;
      const url =
        typeof imgField === "string"
          ? imgField
          : (imgField as Record<string, string>)?.url || "";
      const dataUrl = url.startsWith("data:")
        ? url
        : `data:image/jpeg;base64,${url}`;
      attachments.push({
        id: `${message.id}-file-${idx++}`,
        url: dataUrl,
        type: "file" as const,
        filename: "Image.jpg",
        mediaType: "image/jpeg",
      });
    }

    // File blocks: {"type": "file", "mime_type"/"mimeType": "...", "base64": "...", "filename": "..."}
    if (block.type === "file") {
      const mimeType = (block.mime_type ??
        block.mimeType ??
        "application/octet-stream") as string;
      const base64 = (block.base64 ?? "") as string;
      const filename = (block.filename ?? "file") as string;
      const dataUrl = `data:${mimeType};base64,${base64}`;
      attachments.push({
        id: `${message.id}-file-${idx++}`,
        url: dataUrl,
        type: "file" as const,
        filename,
        mediaType: mimeType,
      });
    }
  }

  return attachments;
}

// ---------------------------------------------------------------------------
// Tool name parsing (reused from old code)
// ---------------------------------------------------------------------------

export const sanitizeToolIdentifier = (value: string): string => {
  const sanitized = value
    .replace(/[^a-zA-Z0-9_-]/g, "_")
    .replace(/^_+|_+$/g, "");
  return sanitized || "tool";
};

export const getToolMetadata = (
  toolName: string,
  knownServerNames: string[],
) => {
  for (const serverName of knownServerNames) {
    const aliases = [serverName, sanitizeToolIdentifier(serverName)];
    for (const alias of aliases) {
      if (toolName === alias || toolName.startsWith(`${alias}_`)) {
        const suffix = toolName.slice(alias.length);
        const name = suffix.startsWith("_") ? suffix.slice(1) : suffix;
        return { serverName, toolName: name || toolName };
      }
    }
  }
  const separatorIndex = toolName.indexOf("_");
  if (separatorIndex === -1) {
    return { serverName: toolName, toolName };
  }
  return {
    serverName: toolName.slice(0, separatorIndex),
    toolName: toolName.slice(separatorIndex + 1),
  };
};

// ---------------------------------------------------------------------------
// Compute tool calls from plain message dicts (for persisted history)
// ---------------------------------------------------------------------------

export type LocalToolCall = {
  id: string;
  call: { name: string; args: Record<string, unknown>; id?: string };
  result: LCMessage | undefined;
  aiMessage: LCMessage;
  index: number;
  state: "pending" | "completed" | "error";
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type SubagentData = SubagentStreamInterface<any, any, any>;

// A chain-of-thought step: a plain tool call, or a subagent call (a `task`
// tool call the SDK paired with its subagent stream).
export type ChainStepData =
  | { kind: "tool"; tc: LocalToolCall }
  | { kind: "subagent"; sub: SubagentData };

// The LangGraph SDK reconstructs subagent containers from history, but it reads
// LangChain's snake_case keys (`tool_calls`, `tool_call_id`, `args.subagent_type`).
// Our axios response interceptor camelCases API payloads, so messages loaded via
// GET /threads/{id} arrive as `toolCalls` / `toolCallId` / `args.subagentType` and
// the SDK builds zero subagents. Restore the snake_case shape the SDK expects
// before handing it the initial values. Streaming is unaffected (SSE bypasses the
// interceptor and is already snake_case).
export function toSdkMessages(messages: LCMessage[]): LCMessage[] {
  return messages.map((msg) => {
    const m = msg as unknown as Record<string, unknown>;
    const out: Record<string, unknown> = { ...m };

    if ("toolCallId" in out) {
      out.tool_call_id = out.toolCallId;
      delete out.toolCallId;
    }

    const toolCalls = (m.toolCalls ?? m.tool_calls) as
      | Array<Record<string, unknown>>
      | undefined;
    if (Array.isArray(toolCalls)) {
      out.tool_calls = toolCalls.map((tc) => {
        // Subagent (task) args carry `subagent_type`; the interceptor
        // camelCased it to `subagentType`. Restore it so the SDK's
        // isValidSubagentType() check passes during reconstruction.
        if (tc.name === "task" && tc.args && typeof tc.args === "object") {
          const args = tc.args as Record<string, unknown>;
          return {
            ...tc,
            args: {
              ...args,
              subagent_type: args.subagent_type ?? args.subagentType,
            },
          };
        }
        return tc;
      });
      delete out.toolCalls;
    }

    return out as unknown as LCMessage;
  });
}

export function computeToolCallsFromMessages(
  messages: LCMessage[],
): LocalToolCall[] {
  // Axios camelCase interceptor converts snake_case keys from the API:
  //   tool_call_id → toolCallId, tool_calls → toolCalls
  // Handle both formats for robustness.
  const getToolCallId = (msg: LCMessage): string | undefined =>
    (msg.tool_call_id ?? msg.toolCallId) as string | undefined;
  const getToolCalls = (msg: LCMessage): LCMessage["tool_calls"] | undefined =>
    msg.tool_calls ?? (msg.toolCalls as LCMessage["tool_calls"]);

  const toolResults = new Map<string, LCMessage>();
  for (const msg of messages) {
    if (msg.type === "tool") {
      const tcId = getToolCallId(msg);
      if (tcId) toolResults.set(tcId, msg);
    }
  }

  const result: LocalToolCall[] = [];
  for (const msg of messages) {
    const toolCalls = getToolCalls(msg);
    if (
      (msg.type === "ai" || msg.type === "assistant") &&
      Array.isArray(toolCalls) &&
      toolCalls.length > 0
    ) {
      for (let i = 0; i < toolCalls.length; i++) {
        const tc = toolCalls[i];
        const tcId = tc.id || `${msg.id}-tc-${i}`;
        const toolMsg = toolResults.get(tcId);
        result.push({
          id: tcId,
          call: { name: tc.name, args: tc.args, id: tc.id },
          result: toolMsg,
          aiMessage: msg,
          index: i,
          state: toolMsg
            ? toolMsg.status === "error"
              ? "error"
              : "completed"
            : "pending",
        });
      }
    }
  }
  return result;
}

// ---------------------------------------------------------------------------
// Map ToolCallWithResult state to AI Elements component state
// ---------------------------------------------------------------------------

export type ToolRenderState =
  | "output-available"
  | "output-error"
  | "approval-requested"
  | "input-available";

export function getToolRenderState(
  tc: LocalToolCall,
  isInterrupted: boolean,
  hitlToolNames?: Set<string> | null,
): ToolRenderState {
  if (tc.state === "completed") return "output-available";
  if (tc.state === "error") return "output-error";
  // pending
  if (isInterrupted && (!hitlToolNames || hitlToolNames.has(tc.call.name))) {
    return "approval-requested";
  }
  return "input-available";
}

// Extracts the set of tool names that require human approval from an HITL
// interrupt payload. Tolerates both snake_case (live SSE) and camelCase
// (rehydrated via the axios interceptor) shapes.
export function extractHitlToolNames(value: unknown): Set<string> | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  const arr = (v.action_requests ?? v.actionRequests) as
    | Array<{ name?: string }>
    | undefined;
  if (!Array.isArray(arr)) return null;
  const names = arr
    .map((r) => (r && typeof r.name === "string" ? r.name : null))
    .filter((n): n is string => n != null);
  return new Set(names);
}

export function getMcpAppInfoFromToolCall(
  tc: LocalToolCall,
): McpAppToolInfo | null {
  const artifact = tc.result?.artifact;
  if (!artifact || typeof artifact !== "object") return null;
  const a = artifact as Record<string, unknown>;
  // Handle both camelCase (Axios/history) and snake_case (stream)
  const resourceUri = (a.mcpAppResourceUri ?? a.mcp_app_resource_uri) as
    | string
    | undefined;
  const serverId = (a.mcpServerId ?? a.mcp_server_id) as string | undefined;
  if (!resourceUri || !serverId) return null;
  return { resourceUri, serverId };
}

export function getStructuredContentFromToolCall(
  tc: LocalToolCall,
): Record<string, unknown> | undefined {
  const artifact = tc.result?.artifact;
  if (!artifact || typeof artifact !== "object") return undefined;
  const a = artifact as Record<string, unknown>;
  // Handle both camelCase (Axios/history) and snake_case (stream/langchain-mcp-adapters)
  const sc = a.structuredContent ?? a.structured_content;
  if (sc && typeof sc === "object") return sc as Record<string, unknown>;
  return undefined;
}

export function getToolOutputContent(tc: LocalToolCall): unknown {
  if (!tc.result) return undefined;
  const content = tc.result.content;
  if (typeof content === "string") {
    try {
      return JSON.parse(content);
    } catch {
      return content;
    }
  }
  return content;
}

// ---------------------------------------------------------------------------
// Pure helpers shared by the chat page and its conversation body: extracting
// content from LangChain message dicts, pairing tool calls with results, and
// normalizing snake_case/camelCase shapes. No React, no state — everything
// here is identity-stable so memoized consumers can rely on their inputs.
// ---------------------------------------------------------------------------

import type { AssembledToolCall } from "@langchain/langgraph-sdk/stream";
import type { AttachmentData } from "@/components/ai-elements/attachments";
import type { LCMessage } from "@/lib/utils/lc-messages";
import type { McpAppToolInfo } from "../components/mcp-app-widget";

export { baseMessageToLC } from "@/lib/utils/lc-messages";
export type { LCMessage, LCToolCallEntry } from "@/lib/utils/lc-messages";

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
  // Anthropic: `thinking` blocks; protocol v1 content: `reasoning` blocks.
  if (Array.isArray(message.content)) {
    const thinking = message.content.filter(
      (c) => c.type === "thinking" || c.type === "reasoning",
    );
    if (thinking.length > 0) {
      return thinking
        .map((c) => ((c.thinking ?? c.reasoning) as string) || "")
        .join("\n");
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
          : ((imgField as Record<string, string> | undefined)?.url ?? "");
      // Absolute URLs pass through untouched; only raw base64 payloads get
      // wrapped into a data URL.
      const dataUrl =
        url.startsWith("data:") || /^https?:\/\//.test(url)
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
  call: { name: string; args?: Record<string, unknown>; id?: string };
  result: LCMessage | undefined;
  aiMessage: LCMessage;
  index: number;
  state: "pending" | "completed" | "error";
};

// A chain-of-thought step: a plain tool call, or a subagent call (a `task`
// tool call paired with its discovered subagent snapshot).
export type ChainStepData =
  | { kind: "tool"; tc: LocalToolCall }
  | { kind: "subagent"; tc: LocalToolCall };

/**
 * Overlay `tools`-channel results onto message-derived tool calls.
 *
 * `computeToolCallsFromMessages` provides the structure (pairing, owning AI
 * message, position); the assembled handles carry what the message
 * projection cannot: live status, the error text, and the MCP artifact the
 * backend wraps into `tool-finished.output` as `{content, artifact}`.
 */
export function enrichToolCalls(
  local: LocalToolCall[],
  assembled: AssembledToolCall[],
): LocalToolCall[] {
  if (assembled.length === 0) return local;
  const byId = new Map(assembled.map((tc) => [tc.id, tc]));
  return local.map((tc) => {
    const live = byId.get(tc.id);
    if (live == null) return tc;
    let { output } = live;
    let artifact: Record<string, unknown> | undefined;
    if (output != null && typeof output === "object" && "artifact" in output) {
      const wrapped = output as { content?: unknown; artifact?: unknown };
      artifact = wrapped.artifact as Record<string, unknown> | undefined;
      output = wrapped.content;
    }
    if (live.status === "error") {
      return {
        ...tc,
        state: "error",
        result: {
          type: "tool",
          content: tc.result?.content ?? live.error ?? "Tool failed",
          status: "error",
          tool_call_id: tc.id,
        },
      };
    }
    if (live.status === "finished") {
      const content =
        tc.result?.content ??
        (typeof output === "string" ? output : JSON.stringify(output ?? ""));
      return {
        ...tc,
        state: "completed",
        result: {
          type: "tool",
          content,
          tool_call_id: tc.id,
          ...(artifact != null || tc.result?.artifact != null
            ? { artifact: tc.result?.artifact ?? artifact }
            : {}),
        },
      };
    }
    return tc;
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
      for (const [i, tc] of toolCalls.entries()) {
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
    | Array<{ name?: string } | null>
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

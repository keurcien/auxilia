"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import Image from "next/image";
import {
  MessageActions,
  MessageAction,
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  Reasoning,
  ReasoningTrigger,
  ReasoningContent,
} from "@/components/ai-elements/reasoning";
import {
  ChainOfThought,
  ChainStep,
  ChainStepIcon,
  NeedsApprovalBadge,
  StepCode,
  StepSection,
  TERMINAL_ICON,
  humanizeToolName,
  isSandboxTool,
  summarizeToolArgs,
} from "@/components/ai-elements/chain-of-thought";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import type { AttachmentData } from "@/components/ai-elements/attachments";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
  Error,
  ErrorContent,
  ErrorDetails,
} from "@/components/ai-elements/error";
import {
  Attachment,
  AttachmentPreview,
  AttachmentHoverCard,
  AttachmentHoverCardTrigger,
  AttachmentInfo,
  AttachmentHoverCardContent,
  getMediaCategory,
  getAttachmentLabel,
  Attachments,
} from "@/components/ai-elements/attachments";
import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { extractToolErrorText } from "@/lib/utils/tool-content";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import ChatPromptInput from "../components/prompt-input";
import {
  RefreshCcwIcon,
  CopyIcon,
  ArchiveIcon,
  CircleSlash,
  Loader2,
  ShieldCheck,
  XCircleIcon,
} from "lucide-react";
import {
  useStream,
  FetchStreamTransport,
} from "@langchain/langgraph-sdk/react";
import type {
  SubagentApi,
  SubagentStreamInterface,
} from "@langchain/langgraph-sdk/ui";
import {
  SubAgentCard,
  SubAgentProgress,
  SynthesisIndicator,
} from "@/components/ai-elements/subagent";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import { useParams } from "next/navigation";
import { api, API_BASE_URL } from "@/lib/api/client";
import { ThinkingLoader } from "../components/loader";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useAgentsStore } from "@/stores/agents-store";
import { canConfigureAgent } from "@/types/agents";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import { useHitlApprovals } from "@/hooks/use-hitl-approvals";
import { useThrottledValue } from "@/hooks/use-throttled-value";
import { useDurableRun, REATTACH_RUN_FIELD } from "@/hooks/use-durable-run";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import {
  McpAppWidget,
  type McpAppToolInfo,
} from "../components/mcp-app-widget";

// ---------------------------------------------------------------------------
// Helpers for extracting content from LangChain messages
// ---------------------------------------------------------------------------

type LCToolCallEntry = {
  name: string;
  args: Record<string, unknown>;
  id?: string;
};

type LCMessage = {
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

function getTextContent(message: LCMessage): string {
  if (typeof message.content === "string") return message.content;
  if (Array.isArray(message.content)) {
    return message.content
      .filter((c) => c.type === "text")
      .map((c) => c.text as string)
      .join("");
  }
  return "";
}

function getReasoningContent(message: LCMessage): string | null {
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

function getFileAttachments(message: LCMessage): AttachmentData[] {
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

const sanitizeToolIdentifier = (value: string): string => {
  const sanitized = value
    .replace(/[^a-zA-Z0-9_-]/g, "_")
    .replace(/^_+|_+$/g, "");
  return sanitized || "tool";
};

const getToolMetadata = (toolName: string, knownServerNames: string[]) => {
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

type LocalToolCall = {
  id: string;
  call: { name: string; args: Record<string, unknown>; id?: string };
  result: LCMessage | undefined;
  aiMessage: LCMessage;
  index: number;
  state: "pending" | "completed" | "error";
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type SubagentData = SubagentStreamInterface<any, any, any>;

// A chain-of-thought step: a plain tool call, or a subagent call (a `task`
// tool call the SDK paired with its subagent stream).
type ChainStepData =
  | { kind: "tool"; tc: LocalToolCall }
  | { kind: "subagent"; sub: SubagentData };

// The LangGraph SDK reconstructs subagent containers from history, but it reads
// LangChain's snake_case keys (`tool_calls`, `tool_call_id`, `args.subagent_type`).
// Our axios response interceptor camelCases API payloads, so messages loaded via
// GET /threads/{id} arrive as `toolCalls` / `toolCallId` / `args.subagentType` and
// the SDK builds zero subagents. Restore the snake_case shape the SDK expects
// before handing it the initial values. Streaming is unaffected (SSE bypasses the
// interceptor and is already snake_case).
function toSdkMessages(messages: LCMessage[]): LCMessage[] {
  return messages.map((msg) => {
    const m = msg as unknown as Record<string, unknown>;
    const out: Record<string, unknown> = { ...m };

    if ("toolCallId" in out) {
      out.tool_call_id = out.toolCallId;
      delete out.toolCallId;
    }

    const toolCalls = (m.toolCalls ?? m.tool_calls) as
      Array<Record<string, unknown>> | undefined;
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

function computeToolCallsFromMessages(messages: LCMessage[]): LocalToolCall[] {
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

type ToolRenderState =
  | "output-available"
  | "output-error"
  | "approval-requested"
  | "input-available";

function getToolRenderState(
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
function extractHitlToolNames(value: unknown): Set<string> | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  const arr = (v.action_requests ?? v.actionRequests) as
    Array<{ name?: string }> | undefined;
  if (!Array.isArray(arr)) return null;
  const names = arr
    .map((r) => (r && typeof r.name === "string" ? r.name : null))
    .filter((n): n is string => n != null);
  return new Set(names);
}

function getMcpAppInfoFromToolCall(tc: LocalToolCall): McpAppToolInfo | null {
  const artifact = tc.result?.artifact;
  if (!artifact || typeof artifact !== "object") return null;
  const a = artifact as Record<string, unknown>;
  // Handle both camelCase (Axios/history) and snake_case (stream)
  const resourceUri = (a.mcpAppResourceUri ?? a.mcp_app_resource_uri) as
    string | undefined;
  const serverId = (a.mcpServerId ?? a.mcp_server_id) as string | undefined;
  if (!resourceUri || !serverId) return null;
  return { resourceUri, serverId };
}

function getStructuredContentFromToolCall(
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

function getToolOutputContent(tc: LocalToolCall): unknown {
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

// ---------------------------------------------------------------------------
// Chat page component
// ---------------------------------------------------------------------------

const ChatPage = () => {
  const params = useParams();
  const agentId = params.id as string;
  const threadId = params.threadId as string;
  const hasInitialized = useRef(false);
  const [threadModel, setThreadModel] = useState<string | undefined>(undefined);
  const [agentArchived, setAgentArchived] = useState(false);
  // Server-computed on GET /threads/{id}: the thread's pinned model is no
  // longer usable (removed from the catalog, provider key gone, or disabled
  // by an admin). Sending would 409, so the composer is replaced by a notice.
  const [modelUnavailable, setModelUnavailable] = useState(false);
  const [viewerRole, setViewerRole] = useState<"admin" | null>(null);
  const [initialValues, setInitialValues] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [rehydratedInterrupt, setRehydratedInterrupt] = useState(false);
  const [rehydratedInterruptValue, setRehydratedInterruptValue] =
    useState<unknown>(null);
  // A failed last run leaves no trace in the checkpoint, so the live stream's
  // error state is lost on reload. Restored from the run record (which
  // persists the error text) when the thread's lastRunStatus says it failed.
  const [rehydratedError, setRehydratedError] = useState<string | null>(null);
  // Subagent internal conversations restored from subgraph checkpoints on
  // refresh, keyed by tool_call_id. The SDK's custom transport doesn't expose a
  // way to inject these into the reconstructed subagents, so we hold them here
  // and pass them to SubAgentCard as a fallback.
  const [subagentMessages, setSubagentMessages] = useState<
    Record<string, unknown[]>
  >({});
  const fetchedSubagentHistory = useRef(new Set<string>());

  const { mcpServers } = useMcpServersStore();
  // Sidebar populates the agents store; when this agent is there and the
  // viewer can edit it, the "not configured" notice points them at the fix
  // instead of telling them to contact the owner (who may be themselves).
  const canConfigure = useAgentsStore((s) =>
    canConfigureAgent(
      s.agents.find((a) => a.id === agentId)?.currentUserPermission,
    ),
  );
  const {
    ready: agentReady,
    status: agentStatus,
    disconnectedMcpServers,
    refetch: refetchReady,
  } = useAgentReadiness(agentArchived ? undefined : agentId);

  const { customFetch, cancel, fetchActiveRunId } = useDurableRun(threadId);

  const transport = useMemo(
    () =>
      new FetchStreamTransport({
        apiUrl: `${API_BASE_URL}/threads/${threadId}/runs/stream`,
        fetch: customFetch,
      }),
    [threadId, customFetch],
  );

  const thread = useStream<Record<string, unknown>>({
    transport,
    threadId,
    initialValues: initialValues ?? { messages: [] },
    messagesKey: "messages",
    filterSubagentMessages: true,
    onFinish: () => {
      // Poll now so the sidebar spinner/badge flips with the stream instead
      // of on the next tick.
      useActiveRunsStore.getState().requestPoll();
      const audio = new Audio("/success.mp3");
      audio.play().catch(() => {});
    },
  } as Parameters<typeof useStream<Record<string, unknown>>>[0]);

  const { isLoading, error, interrupt, submit: rawSubmit, stop } = thread;

  // Once anything is dispatched, the live stream owns interrupt state — drop
  // the rehydrated fallback so it can't shadow a fresh post-resume answer.
  const submit = useCallback<typeof rawSubmit>(
    (input, opts) => {
      setRehydratedInterrupt(false);
      setRehydratedInterruptValue(null);
      setRehydratedError(null);
      return rawSubmit(input, opts);
    },
    [rawSubmit],
  );

  // Stop both server-side (the run outlives this request) and locally.
  const handleStop = useCallback(() => {
    void cancel();
    stop();
  }, [cancel, stop]);

  // The custom transport path exposes subagent methods at runtime but
  // BaseStream types do not include them. Cast to access the API.
  const subagentApi = thread as unknown as SubagentApi;

  // Supervisor todos from stream values
  const streamValues = thread.values as Record<string, unknown>;
  const supervisorTodos = (streamValues?.todos ?? []) as Todo[];

  // Messages: use stream messages when available, else initial.
  // Throttle to ~16Hz so streamed chunks don't trigger per-token re-renders
  // of the whole conversation (and per-token markdown re-parses).
  const streamMessagesRaw = thread.messages as LCMessage[];
  const streamMessages = useThrottledValue(streamMessagesRaw, 60);
  const initMessages = (initialValues?.messages ?? []) as LCMessage[];
  const messages =
    streamMessages.length > 0 || isLoading ? streamMessages : initMessages;

  const isInterrupted = interrupt != null || rehydratedInterrupt;

  // Mid-session race: an admin disabled the model after this page loaded.
  // The gate 409s and use-durable-run rethrows it with this name — lock the
  // send affordances (composer, Retry, HITL approvals) like the on-load flag.
  useEffect(() => {
    if (error instanceof globalThis.Error && error.name === "ModelUnavailableError") {
      setModelUnavailable(true);
    }
  }, [error]);

  // The way back without a page refresh: re-read the server-computed flag
  // (the banner's "Check again") so an admin re-enabling the model unlocks
  // the thread in place.
  const recheckModelAvailability = useCallback(async () => {
    try {
      const response = await api.get(`/threads/${threadId}`);
      setModelUnavailable(response.data.thread.modelAvailable === false);
    } catch {
      // Keep the lock; the user can retry.
    }
  }, [threadId]);

  // The HITL middleware only "hangs" tool calls whose name is in interrupt_on.
  // Other parallel tool calls in the same AI message auto-execute on resume.
  // Scope approval UI and decisions to the hanging subset so the decision count
  // matches the backend's hanging count.
  const hitlToolNames = useMemo(() => {
    const liveValue = (interrupt as { value?: unknown } | null | undefined)
      ?.value;
    return (
      extractHitlToolNames(liveValue) ??
      extractHitlToolNames(rehydratedInterruptValue)
    );
  }, [interrupt, rehydratedInterruptValue]);

  // Tool calls: use stream tool calls when streaming, else compute from messages
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const streamToolCallsRaw = ((thread as any).toolCalls ??
    []) as LocalToolCall[];
  const streamToolCalls = useThrottledValue(streamToolCallsRaw, 60);
  const localToolCalls = useMemo(
    () => computeToolCallsFromMessages(messages),
    [messages],
  );
  const toolCalls =
    streamToolCalls.length > 0 || isLoading ? streamToolCalls : localToolCalls;

  // Index tool calls by AI message id once per render, so the inner map can
  // look them up in O(1) instead of filtering the full list per message.
  const toolCallsByMessageId = useMemo(() => {
    const map = new Map<string, LocalToolCall[]>();
    for (const tc of toolCalls) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const id = (tc.aiMessage as any)?.id as string | undefined;
      if (!id || !tc.call.name) continue;
      const existing = map.get(id);
      if (existing) existing.push(tc);
      else map.set(id, [tc]);
    }
    return map;
  }, [toolCalls]);

  const getToolCallsForMessage = useCallback(
    (message: LCMessage) => {
      if (!message.id) return [];
      return toolCallsByMessageId.get(message.id) ?? [];
    },
    [toolCallsByMessageId],
  );

  // Resolve a subagent_type (sanitize_tool_name(agent.name) backend-side)
  // back to the workspace agent, for its emoji/pastel tile in chain steps.
  const workspaceAgents = useAgentsStore((s) => s.agents);
  const findAgentForSubagentType = useCallback(
    (subagentType: string | undefined) => {
      if (!subagentType) return undefined;
      return (
        workspaceAgents.find(
          (a) => sanitizeToolIdentifier(a.name) === subagentType,
        ) ??
        workspaceAgents.find(
          (a) =>
            a.name.toLowerCase() ===
            subagentType.replaceAll("_", " ").toLowerCase(),
        )
      );
    },
    [workspaceAgents],
  );

  // Loading state detection
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
  const isAwaitingResponse =
    isLoading &&
    lastMsg != null &&
    (lastMsg.type === "human" || lastMsg.type === "user");

  const assistantIsStreaming =
    isLoading &&
    lastMsg != null &&
    (lastMsg.type === "ai" || lastMsg.type === "assistant");

  const consumePendingMessage = usePendingMessageStore(
    (state) => state.consumePendingMessage,
  );
  const knownServerNames = [...mcpServers.map((server) => server.name)].sort(
    (a, b) => b.length - a.length,
  );
  const { setCurrentChat, clearCurrentChat } = useChatHeaderStore();

  // ---- Handlers ----

  const handleSubmit = (message: PromptInputMessage) => {
    if (!message) return;

    const hasText = "text" in message && message.text?.trim();
    const hasFiles =
      "files" in message && message.files && message.files.length > 0;

    if (!hasText && !hasFiles) return;

    // Build LangChain content blocks
    const contentParts: Array<Record<string, unknown>> = [];
    if (hasText) contentParts.push({ type: "text", text: message.text });
    for (const file of message.files ?? []) {
      const fileAny = file as Record<string, unknown>;
      const fileUrl = (fileAny.url as string) || "";
      const mediaType = (fileAny.mediaType as string) || "";

      if (mediaType.startsWith("image/")) {
        // Images: standard LangChain image_url block
        contentParts.push({
          type: "image_url",
          image_url: { url: fileUrl, detail: "auto" },
        });
      } else {
        // Non-image files (PDF, etc.): standard LangChain file block
        // LangChain adapters convert this to provider-native format
        const base64Match = fileUrl.match(/^data:[^;]*;base64,(.*)$/);
        const base64Data = base64Match ? base64Match[1] : fileUrl;
        const filename = (fileAny.filename as string) || "file";
        contentParts.push({
          type: "file",
          mime_type: mediaType || "application/octet-stream",
          base64: base64Data,
          filename,
        });
      }
    }

    const content =
      contentParts.length === 1 && contentParts[0].type === "text"
        ? (contentParts[0].text as string)
        : contentParts;

    submit(
      { messages: [{ type: "human", content }] },
      {
        optimisticValues: {
          messages: [
            ...messages,
            { type: "human", content, id: crypto.randomUUID() },
          ],
        },
        streamSubgraphs: true,
      },
    );
  };

  const pendingToolCalls = useMemo(
    () =>
      toolCalls.filter(
        (tc) =>
          getToolRenderState(tc, isInterrupted, hitlToolNames) ===
          "approval-requested",
      ),
    [toolCalls, isInterrupted, hitlToolNames],
  );

  const { decisions, recordDecision } = useHitlApprovals({
    isInterrupted,
    pendingToolCalls,
    submit: (input, opts) => {
      void submit(input, opts);
    },
    messages,
  });

  const handleRegenerate = () => {
    // Find the last human message and resubmit with regenerate trigger
    const lastHuman = [...messages]
      .reverse()
      .find((m) => m.type === "human" || m.type === "user");
    if (!lastHuman) return;

    submit(
      { messages: [{ type: "human", content: lastHuman.content }] },
      {
        config: {
          configurable: { trigger: "regenerate-message" },
        },
        optimisticValues: { messages },
        streamSubgraphs: true,
      },
    );
  };

  const loadSubagentHistory = useCallback(
    async (toolCallId: string) => {
      const key = `${threadId}:${toolCallId}`;
      if (fetchedSubagentHistory.current.has(key)) return;
      fetchedSubagentHistory.current.add(key);

      try {
        const res = await api.get(
          `/threads/${threadId}/subagents/${toolCallId}/state`,
        );
        const msgs = res.data?.messages;
        if (Array.isArray(msgs) && msgs.length > 0) {
          setSubagentMessages((prev) => ({ ...prev, [toolCallId]: msgs }));
        }
      } catch {
        // Allow a later open to retry a transient failure.
        fetchedSubagentHistory.current.delete(key);
      }
    },
    [threadId],
  );

  // ---- Initialization ----

  useEffect(() => {
    return () => {
      clearCurrentChat();
    };
  }, [clearCurrentChat]);

  useEffect(() => {
    if (hasInitialized.current) return;
    hasInitialized.current = true;

    const initializeChat = async () => {
      const response = await api.get(`/threads/${threadId}`);
      const data = response.data;

      setThreadModel(data.thread.modelId);
      if (data.thread.modelAvailable === false) {
        setModelUnavailable(true);
      }
      const isTriggerThread = data.thread.source === "trigger";
      setCurrentChat({
        agentName: data.thread.agentName ?? null,
        agentEmoji: data.thread.agentEmoji ?? null,
        agentColor: data.thread.agentColor ?? null,
        modelId: data.thread.modelId ?? null,
        // Trigger firings are titled by their trigger; the header shows
        // "<trigger name> / <firing time>" instead of the agent, linking
        // to the trigger's detail page.
        triggerId: isTriggerThread ? (data.thread.triggerId ?? null) : null,
        triggerName: isTriggerThread
          ? (data.thread.firstMessageContent ?? null)
          : null,
        triggerRunAt: isTriggerThread ? (data.thread.createdAt ?? null) : null,
      });

      if (data.thread.agentArchived) {
        setAgentArchived(true);
      }

      if (data.viewerRole === "admin") {
        setViewerRole("admin");
      }

      if (data.interrupted) {
        setRehydratedInterrupt(true);
        if (data.interruptValue !== undefined) {
          setRehydratedInterruptValue(data.interruptValue);
        }
      }

      // If a run is still in flight for this thread, reattach to its live
      // stream rather than rendering the (incomplete) checkpoint. The
      // values replay rebuilds the full conversation, so start from empty
      // to avoid a mid-flight rebuild flicker.
      const activeRunId = await fetchActiveRunId();
      if (activeRunId) {
        setInitialValues({ messages: [] });
        // Use the `submit` wrapper (not rawSubmit) so any rehydrated HITL
        // state is cleared before the live replayed run owns it.
        setTimeout(() => {
          submit(
            {
              [REATTACH_RUN_FIELD]: activeRunId,
            } as Parameters<typeof submit>[0],
            { streamSubgraphs: true } as Parameters<typeof submit>[1],
          );
        }, 0);
        return;
      }

      const values = data.values || { messages: [] };
      // Restore snake_case message keys so the SDK can reconstruct subagents.
      const normalizedValues = {
        ...values,
        messages: toSdkMessages((values.messages ?? []) as LCMessage[]),
      };

      const pendingMessage = consumePendingMessage(threadId);
      if (pendingMessage) {
        // Set initial values first so submit has proper history base
        setInitialValues(normalizedValues);
        // Defer submit to next tick so initialValues takes effect
        setTimeout(() => {
          handleSubmit(pendingMessage);
        }, 0);
      } else {
        setInitialValues(normalizedValues);
        // No run in flight and none about to start: if the last run failed,
        // restore its error from the run record so a reload doesn't hide it.
        const lastRunStatus = data.thread.lastRunStatus as string | undefined;
        if (lastRunStatus === "error" || lastRunStatus === "timeout") {
          const fallback =
            lastRunStatus === "timeout"
              ? "The last run exceeded the time limit."
              : "The last run failed.";
          try {
            const res = await api.get(`/threads/${threadId}/runs`);
            const runs = (res.data ?? []) as {
              status?: string;
              error?: string | null;
            }[];
            // Newest first; the run that stamped lastRunStatus is the first
            // failed one.
            const failed = runs.find(
              (r) => r.status === "error" || r.status === "timeout",
            );
            setRehydratedError(failed?.error || fallback);
          } catch {
            setRehydratedError(fallback);
          }
        }
      }
    };

    initializeChat();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  // ---- Chain-of-thought grouping ----
  // One timeline per run of *consecutive* tool work: steps from adjacent AI
  // messages merge into the run's first step-bearing AI message, but any
  // assistant text ends the run — a message's own steps render above its
  // text, and tool calls after the text start a new chain below it. Task
  // tool calls pair with their SDK subagent stream by id, preserving the
  // original tool_call order.
  const chainByOwner = new Map<string, ChainStepData[]>();
  {
    let turnOwner: string | null = null;
    for (const m of messages) {
      if (m.type === "human" || m.type === "user") {
        turnOwner = null;
        continue;
      }
      if ((m.type !== "ai" && m.type !== "assistant") || !m.id) continue;
      const hasText = getTextContent(m).trim().length > 0;
      const tcs = getToolCallsForMessage(m);
      const subs = subagentApi.getSubagentsByMessage(m.id);
      if (tcs.length === 0 && subs.length === 0) {
        if (hasText) turnOwner = null;
        continue;
      }

      const subById = new Map(subs.map((s) => [s.id, s]));
      const paired = new Set<string>();
      const steps: ChainStepData[] = [];
      for (const tc of tcs) {
        const sub = subById.get(tc.id);
        if (sub) {
          steps.push({ kind: "subagent", sub });
          paired.add(sub.id);
        } else {
          steps.push({ kind: "tool", tc });
        }
      }
      for (const sub of subs) {
        if (!paired.has(sub.id)) steps.push({ kind: "subagent", sub });
      }

      if (turnOwner == null) {
        turnOwner = m.id;
        chainByOwner.set(m.id, steps);
      } else {
        chainByOwner.get(turnOwner)?.push(...steps);
      }
      // The message's text renders below its steps — anything after it
      // belongs to a fresh chain.
      if (hasText) turnOwner = null;
    }
  }

  // ---- Render ----

  return (
    <div className="h-full flex flex-col w-full overflow-hidden">
      <div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
        <Conversation>
          <ConversationContent className="max-w-4xl mx-auto w-full lg:px-10 sm:px-6 px-2">
            {supervisorTodos.length > 0 && (
              <TodoList
                todos={supervisorTodos}
                className="mb-4 rounded-lg border border-border/50 bg-muted/30 p-4"
              />
            )}
            {messages.map((message, messageIndex) => {
              // Skip tool messages — they're rendered via toolCalls pairing
              if (message.type === "tool") return null;

              // ---- Human message ----
              if (message.type === "human" || message.type === "user") {
                const text = getTextContent(message);
                const attachments = getFileAttachments(message);

                return (
                  <Fragment key={message.id ?? messageIndex}>
                    {attachments.length > 0 && (
                      <div className="flex justify-end">
                        <Attachments variant="inline">
                          {attachments.map((attachment) => {
                            const mediaCategory = getMediaCategory(attachment);
                            const label = getAttachmentLabel(attachment);
                            return (
                              <AttachmentHoverCard key={attachment.id}>
                                <AttachmentHoverCardTrigger asChild>
                                  <Attachment data={attachment}>
                                    <div className="relative size-5 shrink-0">
                                      <div className="absolute inset-0 transition-opacity group-hover:opacity-0">
                                        <AttachmentPreview />
                                      </div>
                                    </div>
                                    <AttachmentInfo />
                                  </Attachment>
                                </AttachmentHoverCardTrigger>
                                <AttachmentHoverCardContent>
                                  <div className="space-y-3">
                                    {mediaCategory === "image" &&
                                      "url" in attachment &&
                                      attachment.url && (
                                        <div className="flex items-center justify-center overflow-hidden rounded-md border">
                                          <Image
                                            alt={label}
                                            className="object-contain"
                                            height={200}
                                            src={attachment.url as string}
                                            width={200}
                                          />
                                        </div>
                                      )}
                                    <div className="space-y-1 px-0.5">
                                      <h4 className="font-semibold text-sm leading-none">
                                        {label}
                                      </h4>
                                    </div>
                                  </div>
                                </AttachmentHoverCardContent>
                              </AttachmentHoverCard>
                            );
                          })}
                        </Attachments>
                      </div>
                    )}
                    {text && (
                      <Message from="user">
                        <MessageContent>
                          <MessageResponse>{text}</MessageResponse>
                        </MessageContent>
                      </Message>
                    )}
                  </Fragment>
                );
              }

              // ---- AI message ----
              if (message.type === "ai" || message.type === "assistant") {
                const text = getTextContent(message);
                const reasoning = getReasoningContent(message);
                const chainSteps = message.id
                  ? (chainByOwner.get(message.id) ?? [])
                  : [];
                const chainSubagents = chainSteps
                  .filter(
                    (s): s is Extract<ChainStepData, { kind: "subagent" }> =>
                      s.kind === "subagent",
                  )
                  .map((s) => s.sub);
                const chainActive = chainSteps.some((s) =>
                  s.kind === "tool"
                    ? s.tc.state === "pending"
                    : s.sub.status === "running" || s.sub.status === "pending",
                );
                const chainLockOpen = chainSteps.some(
                  (s) =>
                    s.kind === "tool" &&
                    getToolRenderState(s.tc, isInterrupted, hitlToolNames) ===
                      "approval-requested" &&
                    !decisions[s.tc.id],
                );
                const isTaskCall = (tc: LocalToolCall) =>
                  tc.call.name === "task";
                const toolCount = chainSteps.filter(
                  (s) => s.kind === "tool" && !isTaskCall(s.tc),
                ).length;
                const subagentCount = chainSteps.length - toolCount;
                const isLastMessage =
                  messageIndex === messages.length - 1 ||
                  // Last AI message before a potential loading indicator
                  (messageIndex === messages.length - 2 &&
                    messages[messages.length - 1]?.type === "tool");
                const isLastAiMessage =
                  !isLoading && isLastMessage && text.length > 0;

                return (
                  <Fragment key={message.id ?? messageIndex}>
                    {/* Reasoning / thinking */}
                    {reasoning && (
                      <Reasoning
                        className="w-full"
                        isStreaming={assistantIsStreaming && isLastMessage}
                      >
                        <ReasoningTrigger />
                        <ReasoningContent>{reasoning}</ReasoningContent>
                      </Reasoning>
                    )}

                    {/* Chain of thought: the turn's tool + subagent steps */}
                    {chainSteps.length > 0 && (
                      <div className="w-full space-y-2">
                        <ChainOfThought
                          active={chainActive}
                          lockOpen={chainLockOpen}
                          toolCount={toolCount}
                          subagentCount={subagentCount}
                        >
                          {chainSteps.map((step) => {
                            if (step.kind === "subagent") {
                              const sub = step.sub;
                              return (
                                <SubAgentCard
                                  key={sub.id}
                                  subagent={sub}
                                  mcpServers={mcpServers}
                                  agent={findAgentForSubagentType(
                                    sub.toolCall?.args?.subagent_type as
                                      | string
                                      | undefined,
                                  )}
                                  onOpen={
                                    sub.messages.length === 0 &&
                                    (sub.status === "complete" ||
                                      sub.status === "error")
                                      ? () => void loadSubagentHistory(sub.id)
                                      : undefined
                                  }
                                  fallbackMessages={subagentMessages[sub.id]}
                                />
                              );
                            }

                            const tc = step.tc;
                            const toolState = getToolRenderState(
                              tc,
                              isInterrupted,
                              hitlToolNames,
                            );
                            const decided = decisions[tc.id];
                            const output = getToolOutputContent(tc);
                            const errorText =
                              tc.state === "error" && tc.result
                                ? extractToolErrorText(tc.result.content)
                                : undefined;
                            const stepMeta =
                              toolState === "approval-requested" ? (
                                <NeedsApprovalBadge />
                              ) : toolState === "input-available" ? (
                                <Loader2 className="size-3 animate-spin text-petrol" />
                              ) : toolState === "output-error" ? (
                                <XCircleIcon className="size-3.5 text-destructive" />
                              ) : undefined;
                            const approvalFooter =
                              toolState === "approval-requested" ? (
                                <div className="flex items-center gap-2 pt-1">
                                  <button
                                    type="button"
                                    disabled={
                                      decided != null || modelUnavailable
                                    }
                                    onClick={() => {
                                      recordDecision(tc.id, "approve");
                                    }}
                                    className={cn(
                                      "cursor-pointer rounded-[7px] bg-petrol px-4 py-1.5 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed",
                                      decided === "reject" && "opacity-40",
                                    )}
                                  >
                                    Approve
                                  </button>
                                  <button
                                    type="button"
                                    disabled={
                                      decided != null || modelUnavailable
                                    }
                                    onClick={() => {
                                      recordDecision(tc.id, "reject");
                                    }}
                                    className={cn(
                                      "cursor-pointer rounded-[7px] border border-input bg-card px-4 py-1.5 text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover disabled:cursor-not-allowed",
                                      decided === "approve" && "opacity-40",
                                    )}
                                  >
                                    Deny
                                  </button>
                                </div>
                              ) : null;
                            const resultSection =
                              errorText !== undefined ? (
                                <StepSection label="ERROR" error>
                                  <StepCode value={errorText} />
                                </StepSection>
                              ) : (
                                output !== undefined && (
                                  <StepSection label="RESULT">
                                    <StepCode value={output} />
                                  </StepSection>
                                )
                              );

                            if (isTaskCall(tc)) {
                              // task call the SDK didn't pair with a subagent
                              // stream (e.g. filtered history) — still render
                              // it as a subagent-style step.
                              const args = tc.call.args as
                                | Record<string, unknown>
                                | undefined;
                              const subagentType = (args?.subagent_type ??
                                args?.subagentType) as string | undefined;
                              const matched =
                                findAgentForSubagentType(subagentType);
                              const description = args?.description as
                                | string
                                | undefined;
                              return (
                                <ChainStep
                                  key={tc.id}
                                  node={
                                    <AgentAvatar
                                      color={matched?.color}
                                      emoji={matched?.emoji}
                                      size="2xs"
                                      className="relative z-[1]"
                                    />
                                  }
                                  title={`Ask ${matched?.name ?? subagentType?.replaceAll("_", " ") ?? "subagent"}`}
                                  summary={description}
                                  meta={stepMeta}
                                  lockOpen={
                                    toolState === "approval-requested" &&
                                    !decided
                                  }
                                >
                                  {description && (
                                    <StepSection label="TASK">
                                      <StepCode value={description} />
                                    </StepSection>
                                  )}
                                  {resultSection}
                                  {approvalFooter}
                                </ChainStep>
                              );
                            }

                            const sandbox = isSandboxTool(tc.call.name);
                            const { serverName, toolName } = sandbox
                              ? {
                                  serverName: "Code execution",
                                  toolName: tc.call.name,
                                }
                              : getToolMetadata(
                                  tc.call.name,
                                  knownServerNames,
                                );
                            return (
                              <ChainStep
                                key={tc.id}
                                node={
                                  <ChainStepIcon
                                    icon={
                                      sandbox
                                        ? TERMINAL_ICON
                                        : mcpServers.find(
                                            (server) =>
                                              server.name === serverName,
                                          )?.iconUrl
                                    }
                                    name={serverName}
                                  />
                                }
                                title={humanizeToolName(toolName)}
                                summary={summarizeToolArgs(tc.call.args)}
                                meta={stepMeta}
                                lockOpen={
                                  toolState === "approval-requested" &&
                                  !decided
                                }
                              >
                                {tc.call.args !== undefined && (
                                  <StepSection label="PARAMETERS">
                                    <StepCode value={tc.call.args} />
                                  </StepSection>
                                )}
                                {resultSection}
                                {approvalFooter}
                              </ChainStep>
                            );
                          })}
                        </ChainOfThought>
                        {chainSubagents.length > 0 && (
                          <>
                            <SubAgentProgress subagents={chainSubagents} />
                            <SynthesisIndicator
                              subagents={chainSubagents}
                              isCoordinatorStreaming={
                                assistantIsStreaming && isLastMessage
                              }
                            />
                          </>
                        )}
                        {/* Interactive MCP app widgets surface below the chain */}
                        {chainSteps.map((step) => {
                          if (step.kind !== "tool") return null;
                          const appToolInfo = getMcpAppInfoFromToolCall(
                            step.tc,
                          );
                          if (!appToolInfo) return null;
                          return (
                            <McpAppWidget
                              key={`app-${step.tc.id}`}
                              input={step.tc.call.args}
                              output={getToolOutputContent(step.tc)}
                              structuredContent={getStructuredContentFromToolCall(
                                step.tc,
                              )}
                              errorText={
                                step.tc.state === "error" && step.tc.result
                                  ? extractToolErrorText(step.tc.result.content)
                                  : undefined
                              }
                              toolName={
                                getToolMetadata(
                                  step.tc.call.name,
                                  knownServerNames,
                                ).toolName
                              }
                              appToolInfo={appToolInfo}
                            />
                          );
                        })}
                      </div>
                    )}

                    {/* Text content */}
                    {text && (
                      <>
                        <Message from="assistant">
                          <MessageContent>
                            <MessageResponse>{text}</MessageResponse>
                          </MessageContent>
                        </Message>
                        {isLastAiMessage && (
                          <MessageActions>
                            {!modelUnavailable && (
                              <MessageAction
                                onClick={handleRegenerate}
                                label="Retry"
                              >
                                <RefreshCcwIcon className="size-3" />
                              </MessageAction>
                            )}
                            <MessageAction
                              onClick={() => {
                                void navigator.clipboard.writeText(text);
                              }}
                              label="Copy"
                            >
                              <CopyIcon className="size-3" />
                            </MessageAction>
                          </MessageActions>
                        )}
                      </>
                    )}
                  </Fragment>
                );
              }

              return null;
            })}

            {/* Loading indicator */}
            {isAwaitingResponse && (
              <div>
                <Message from="assistant">
                  <div className="w-full flex flex-col gap-2">
                    <MessageContent>
                      <ThinkingLoader className="px-0" />
                    </MessageContent>
                  </div>
                </Message>
              </div>
            )}

            {/* Streaming indicator when AI has started but text is still coming */}
            {assistantIsStreaming &&
              lastMsg !== null &&
              getTextContent(lastMsg).length === 0 &&
              !getToolCallsForMessage(lastMsg).length && (
                <div>
                  <Message from="assistant">
                    <div className="w-full flex flex-col gap-2">
                      <MessageContent>
                        <ThinkingLoader className="px-0" />
                      </MessageContent>
                    </div>
                  </Message>
                </div>
              )}

            {(error != null || rehydratedError != null) && (
              <Error>
                <ErrorContent>An error occurred.</ErrorContent>
                <ErrorDetails>
                  <div>
                    {error != null
                      ? error instanceof globalThis.Error
                        ? error.message
                        : String(error)
                      : rehydratedError}
                  </div>
                </ErrorDetails>
              </Error>
            )}
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
        <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-background to-transparent z-10" />
      </div>
      <div className="w-full shrink-0 bg-background">
        {viewerRole === "admin" ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
              <ShieldCheck className="size-5 shrink-0 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Viewing as admin — this thread belongs to another user and is
                read-only.
              </p>
            </div>
          </div>
        ) : agentArchived ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
              <ArchiveIcon className="size-5 shrink-0 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                The agent linked to this conversation has been archived. This
                thread is preserved as read-only so you can still review your
                past messages.
              </p>
            </div>
          </div>
        ) : modelUnavailable ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
              <CircleSlash className="size-5 shrink-0 text-muted-foreground" />
              <p className="flex-1 text-sm text-muted-foreground">
                The model used by this conversation
                {threadModel ? ` (${threadModel})` : ""} is no longer available
                in this workspace. Ask a workspace admin to restore it, or
                start a new conversation.
              </p>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0 cursor-pointer"
                onClick={() => {
                  void recheckModelAvailability();
                }}
              >
                Check again
              </Button>
            </div>
          </div>
        ) : agentStatus === "not_configured" ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-4">
            <div className="w-full flex items-center justify-center border border-destructive/30 bg-destructive/10 rounded-lg px-4 py-8">
              <p className="text-md text-center text-destructive">
                {canConfigure
                  ? "This agent's MCP tools aren't configured yet. Configure them in the agent's settings."
                  : "Agent is not configured yet. Contact agent owner to configure it first."}
              </p>
            </div>
          </div>
        ) : (
          <ChatPromptInput
            onSubmit={handleSubmit}
            status={isLoading ? "streaming" : "ready"}
            className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-4"
            stop={handleStop}
            selectedModel={threadModel}
            readOnlyModel={true}
            agentReady={agentReady}
            disconnectedServers={disconnectedMcpServers}
            onAllConnected={refetchReady}
          />
        )}
      </div>
    </div>
  );
};

export default ChatPage;

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import ChatPromptInput from "../components/prompt-input";
import { ArchiveIcon, CircleSlash, ShieldCheck } from "lucide-react";
import {
  useStream,
  FetchStreamTransport,
} from "@langchain/langgraph-sdk/react";
import type { SubagentApi } from "@langchain/langgraph-sdk/ui";
import type { Todo } from "@/components/ai-elements/todo-list";
import { useParams } from "next/navigation";
import { api, API_BASE_URL } from "@/lib/api/client";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useAgentsStore } from "@/stores/agents-store";
import { canConfigureAgent } from "@/types/agents";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import { useHitlApprovals } from "@/hooks/use-hitl-approvals";
import { useThrottledValue } from "@/hooks/use-throttled-value";
import { useStreamTick } from "@/hooks/use-stream-tick";
import { useDurableRun, REATTACH_RUN_FIELD } from "@/hooks/use-durable-run";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { ConversationBody } from "./conversation-body";
import {
  type LCMessage,
  computeToolCallsFromMessages,
  extractHitlToolNames,
  getToolRenderState,
  toSdkMessages,
} from "./message-helpers";

// Stable fallback so `values.todos ?? []` doesn't mint a new identity per
// render and defeat the memoized conversation body.
const EMPTY_TODOS: Todo[] = [];

// ---------------------------------------------------------------------------
// Chat page component
// ---------------------------------------------------------------------------

const ChatPage = () => {
  const params = useParams();
  const agentId = params.id as string;
  const threadId = params.threadId as string;
  const hasInitialized = useRef(false);
  const [threadModel, setThreadModel] = useState<string | undefined>(undefined);
  // The thread's pinned reasoning-effort choice (null = model default) —
  // displayed read-only next to the pinned model.
  const [threadEffort, setThreadEffort] = useState<string | null>(null);
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
  const [rehydratedInterruptId, setRehydratedInterruptId] = useState<
    string | null
  >(null);
  // A failed last run leaves no trace in the checkpoint, so the live stream's
  // error state is lost on reload. Restored from the run record (which
  // persists the error text) when the thread's lastRunStatus says it failed.
  const [rehydratedError, setRehydratedError] = useState<string | null>(null);
  // Set on submit so a still-in-flight rehydration fetch can't restore the
  // previous run's error after the new run already owns the error state.
  const rehydratedErrorStale = useRef(false);

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
    // Coalesce same-tick SSE bursts into one listener notification per
    // macrotask (reattach replay is the worst case). Do NOT pass a number
    // here — the SDK implements numeric throttle as a trailing debounce,
    // which starves updates under a continuous token flow.
    throttle: true,
    onError: (err: unknown) => {
      if (!(err instanceof globalThis.Error)) return;
      // Mid-session race: an admin disabled the model after this page
      // loaded. The gate 409s and use-durable-run rethrows it with this
      // name — lock the send affordances (composer, Retry, HITL approvals)
      // like the on-load flag.
      if (err.name === "ModelUnavailableError") {
        setModelUnavailable(true);
      }
      // A 409 stale_interrupt means this view resumed an approval that was
      // already handled elsewhere (another tab, Slack). The checkpoint is
      // the truth — reload so the thread renders its actual state instead
      // of the stale cards.
      if (err.name === "StaleInterruptError") {
        window.location.reload();
      }
    },
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
      setRehydratedInterruptId(null);
      setRehydratedError(null);
      rehydratedErrorStale.current = true;
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
  // BaseStream types do not include them. Cast to access the API. The ref
  // indirection gives the memoized conversation body an identity-stable
  // lookup — the SDK rebuilds the thread object on every render, but every
  // snapshot delegates to the same underlying StreamManager, so a
  // one-render-stale ref still reads live subagent state.
  const subagentApiRef = useRef(thread as unknown as SubagentApi);
  useEffect(() => {
    subagentApiRef.current = thread as unknown as SubagentApi;
  });
  const getSubagentsByMessage = useCallback(
    (messageId: string) =>
      subagentApiRef.current.getSubagentsByMessage(messageId),
    [],
  );

  // Bumps ≤16Hz on stream notifications; lets the memoized conversation body
  // follow subagent-only updates (which change no other prop identity).
  const streamTick = useStreamTick(60);

  // Supervisor todos from stream values
  const streamValues = thread.values as Record<string, unknown>;
  const supervisorTodos = (streamValues?.todos ?? EMPTY_TODOS) as Todo[];

  // Messages: use stream messages when available, else initial.
  // Throttle to ~16Hz so streamed chunks don't trigger per-token re-renders
  // of the whole conversation (and per-token markdown re-parses).
  const streamMessagesRaw = thread.messages as LCMessage[];
  const streamMessages = useThrottledValue(streamMessagesRaw, 60);
  const initMessages = (initialValues?.messages ?? []) as LCMessage[];
  const messages =
    streamMessages.length > 0 || isLoading ? streamMessages : initMessages;

  const isInterrupted = interrupt != null || rehydratedInterrupt;

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

  // The pending interrupt's stable id (from the live SSE payload, or the
  // thread read after a refresh). Echoed back on resume so a stale approval
  // — already handled from another surface — is a 409, not a resume of
  // whatever the thread is paused on now.
  const interruptId =
    (interrupt as { id?: string } | null | undefined)?.id ??
    rehydratedInterruptId;

  // Tool calls, derived once per (throttled) messages change. The SDK also
  // exposes a `toolCalls` getter, but it rescans every message on each
  // property read — per render, per token — so we never touch it.
  const toolCalls = useMemo(
    () => computeToolCallsFromMessages(messages),
    [messages],
  );

  const consumePendingMessage = usePendingMessageStore(
    (state) => state.consumePendingMessage,
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

  // The addressed resume echoes tool-call ids the backend re-derives from
  // the checkpoint. A tool call persisted without an id gets a synthesized
  // `${msg.id}-tc-${i}` here but `approval-${i}` on the backend — those can
  // never match, so fall back to the positional form for that batch.
  const pendingIdsAreReal = pendingToolCalls.every((tc) => tc.call.id);
  const { decisions, recordDecision } = useHitlApprovals({
    isInterrupted,
    interruptId: pendingIdsAreReal ? (interruptId ?? null) : null,
    pendingToolCalls,
    submit: (input, opts) => {
      void submit(input, opts);
    },
    messages,
  });

  const handleRegenerate = useCallback(() => {
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
  }, [messages, submit]);

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
      setThreadEffort(data.thread.reasoningEffort ?? null);
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
        setRehydratedInterruptId((data.interruptId as string | undefined) ?? null);
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
            if (!rehydratedErrorStale.current) {
              setRehydratedError(failed?.error || fallback);
            }
          } catch {
            if (!rehydratedErrorStale.current) {
              setRehydratedError(fallback);
            }
          }
        }
      }
    };

    initializeChat();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId]);

  // ---- Render ----

  return (
    <div className="h-full flex flex-col w-full overflow-hidden">
      <div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
        <Conversation>
          <ConversationContent className="max-w-4xl mx-auto w-full lg:px-10 sm:px-6 px-2">
            <ConversationBody
              threadId={threadId}
              messages={messages}
              toolCalls={toolCalls}
              getSubagentsByMessage={getSubagentsByMessage}
              supervisorTodos={supervisorTodos}
              isLoading={isLoading}
              isInterrupted={isInterrupted}
              hitlToolNames={hitlToolNames}
              decisions={decisions}
              recordDecision={recordDecision}
              modelUnavailable={modelUnavailable}
              onRegenerate={handleRegenerate}
              error={error}
              rehydratedError={rehydratedError}
              streamTick={streamTick}
            />
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
            selectedEffort={threadEffort}
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

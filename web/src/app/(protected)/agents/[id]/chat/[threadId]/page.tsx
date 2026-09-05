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
import { isHumanMessage } from "@langchain/core/messages";
import { useStream } from "@langchain/react";
import type { AnyStream } from "@langchain/react";
import type { Todo } from "@/components/ai-elements/todo-list";
import { useParams } from "next/navigation";
import { api, API_BASE_URL } from "@/lib/api/client";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useAgentsStore } from "@/stores/agents-store";
import { canConfigureAgent } from "@/types/agents";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import { type HitlResponse, useHitlApprovals } from "@/hooks/use-hitl-approvals";
import { useThrottledValue } from "@/hooks/use-throttled-value";
import { useProtocolFetch } from "@/hooks/use-protocol-fetch";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { ConversationBody } from "./conversation-body";
import {
  extractHitlToolNames,
  getToolStepState,
  splitInterrupts,
  pairToolCalls,
} from "./message-helpers";

// Stable fallback so `values.todos ?? []` doesn't mint a new identity per
// render and defeat the memoized conversation body.
const EMPTY_TODOS: Todo[] = [];

// The protocol client builds absolute request URLs (`new URL(apiUrl + path)`),
// so the browser-side relative proxy base must be absolutized. Guarded for
// the SSR pass of this client component, where no requests are ever fired.
const PROTOCOL_API_URL =
  typeof window === "undefined"
    ? API_BASE_URL
    : new URL(API_BASE_URL, window.location.origin).toString();

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

  const protocolFetch = useProtocolFetch(threadId, {
    // Mid-session race: an admin disabled the model after this page loaded.
    // The command 409s — lock the send affordances like the on-load flag.
    onModelUnavailable: () => {
      setModelUnavailable(true);
    },
    // A 409 stale_interrupt means this view resumed an approval that was
    // already handled elsewhere (another tab, Slack). The checkpoint is the
    // truth — reload so the thread renders its actual state.
    onStaleInterrupt: () => {
      window.location.reload();
    },
  });

  // Agent Streaming Protocol stack (issue #309 Part 2): hydration via
  // GET /threads/{id}/state, commands via POST /threads/{id}/commands, and
  // one shared filtered SSE session on POST /threads/{id}/stream/events.
  // Reattach-to-in-flight-run and interrupt rehydration are built in (the
  // activity gate reads `next`/`tasks` from the state snapshot).
  const stream = useStream({
    assistantId: agentId,
    apiUrl: PROTOCOL_API_URL,
    threadId,
    messagesKey: "messages",
    fetch: protocolFetch,
    onCompleted: () => {
      // Poll now so the sidebar spinner/badge flips with the stream instead
      // of on the next tick.
      useActiveRunsStore.getState().requestPoll();
      const audio = new Audio("/success.mp3");
      audio.play().catch(() => {});
    },
  });

  const { isLoading, error, interrupts } = stream;
  // The root interrupt drives the root chain's approval UI; a subagent's
  // (namespaced) interrupt is handed to its card, which approves it itself.
  // The hook rebuilds the `interrupts` array on every store tick, so hold the
  // last array whose content (ids + namespaces) changed and split that one —
  // otherwise the memoized body would re-render at token rate. Adjusting
  // state during render is React's pattern for state derived from props.
  const interruptsKey = interrupts
    .map((i) => `${i.id ?? ""}@${(i.namespace ?? []).join("/")}`)
    .join(",");
  const [heldInterrupts, setHeldInterrupts] = useState({
    key: interruptsKey,
    list: interrupts,
  });
  if (heldInterrupts.key !== interruptsKey) {
    setHeldInterrupts({ key: interruptsKey, list: interrupts });
  }
  const { root: interrupt, nested: nestedInterrupts } = useMemo(
    () => splitInterrupts(heldInterrupts.list),
    [heldInterrupts],
  );

  // Identity-stable handle for selector hooks inside memoized children
  // (SubAgentCard's scoped useMessages/useValues) and for callbacks that
  // must not churn at token rate. The hook return is rebuilt per store
  // flush, but its controller — and every method, which just delegates to
  // it — is created once per mount (the controller's deps are our constant
  // options), so the first snapshot stays a live, valid handle.
  const [selectorStream] = useState<AnyStream>(() => stream as AnyStream);

  // Stop both server-side (the SDK cancels the active run via
  // /runs/{id}/cancel) and locally.
  const handleStop = useCallback(() => {
    void selectorStream.stop();
    useActiveRunsStore.getState().requestPoll();
  }, [selectorStream]);

  // Supervisor todos from the root values snapshot.
  const streamValues = stream.values as Record<string, unknown>;
  const supervisorTodos = (streamValues.todos ?? EMPTY_TODOS) as Todo[];

  // Messages: BaseMessage instances from the projection, mapped (per-instance
  // cached) to the plain dicts the rendering layer consumes, throttled to
  // ~16Hz so store flushes during token streams don't re-render the
  // conversation more often than the eye can follow.
  const messages = useThrottledValue(stream.messages, 60);

  const isInterrupted = interrupt != null;
  const interruptId = interrupt?.id ?? null;

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
  const hitlToolNames = useMemo(
    () => extractHitlToolNames(interrupt?.value),
    [interrupt],
  );

  // Tool calls: structure derived from the throttled messages, live state
  // (status / errors / MCP artifacts) overlaid from the `tools` channel.
  const streamToolCalls = useThrottledValue(stream.toolCalls, 60);
  const toolCalls = useMemo(
    () => pairToolCalls(messages, streamToolCalls),
    [messages, streamToolCalls],
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
      const fileUrl = file.url;
      const mediaType = file.mediaType;

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
        const filename = file.filename || "file";
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

    rehydratedErrorStale.current = true;
    setRehydratedError(null);
    // Optimistic echo of the input is built into the stream stack.
    void stream.submit({ messages: [{ type: "human", content }] });
  };

  const pendingToolCalls = useMemo(
    () =>
      toolCalls.filter(
        (tc) =>
          getToolStepState(tc, isInterrupted, hitlToolNames) ===
          "awaiting-approval",
      ),
    [toolCalls, isInterrupted, hitlToolNames],
  );

  // A tool call persisted without an id gets `<message>-tc-<i>` here but
  // `approval-<i>` on the backend — those never match, so such a batch is
  // resumed positionally instead of addressed.
  const pendingIdsAreReal = pendingToolCalls.every((tc) => tc.callId != null);
  const respondToInterrupt = useCallback(
    (response: HitlResponse, addressedId: string | null) => {
      rehydratedErrorStale.current = true;
      setRehydratedError(null);
      // The protocol's `input.respond`: the backend maps it onto a resume run
      // and stale-checks the interrupt id against the checkpoint (409).
      void selectorStream.respond(
        response,
        addressedId != null ? { interruptId: addressedId } : undefined,
      );
    },
    [selectorStream],
  );
  const { decisions, recordDecision } = useHitlApprovals({
    interruptId: pendingIdsAreReal ? interruptId : null,
    pendingToolCalls,
    respond: respondToInterrupt,
  });

  const handleRegenerate = useCallback(() => {
    // Find the last human message and resubmit with regenerate trigger
    const lastHuman = [...messages]
      .reverse()
      .find(isHumanMessage);
    if (!lastHuman) return;

    rehydratedErrorStale.current = true;
    setRehydratedError(null);
    void selectorStream.submit(
      { messages: [{ type: "human", content: lastHuman.content }] },
      { config: { configurable: { trigger: "regenerate-message" } } },
    );
  }, [messages, selectorStream]);

  // ---- Initialization (thread metadata; conversation state hydrates via
  // the protocol stack's GET /threads/{id}/state) ----

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

      const pendingMessage = consumePendingMessage(threadId);
      if (pendingMessage) {
        // Order the first submit AFTER hydration settles. Hydrate's
        // converge-to-server-truth step drops optimistic messages the state
        // snapshot doesn't contain — on a brand-new thread that snapshot is
        // empty, so a submit racing the in-flight hydrate loses its
        // optimistic echo (the user's message vanishes until the wire echo
        // lands). Normally resolves in milliseconds; the timeout bounds a
        // hung /state fetch so the consumed pending message always submits.
        const hydrationSettled = Promise.race([
          stream.hydrationPromise.catch(() => {}),
          new Promise((resolve) => setTimeout(resolve, 4_000)),
        ]);
        hydrationSettled
          .then(() => {
            handleSubmit(pendingMessage);
          })
          .catch((err: unknown) => {
            console.error("Pending message submit failed:", err);
          });
        return;
      }

      // If the last run failed, restore its error from the run record so a
      // reload doesn't hide it (a failed run leaves no checkpoint trace).
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
              messages={messages}
              toolCalls={toolCalls}
              subagents={stream.subagents}
              stream={selectorStream}
              supervisorTodos={supervisorTodos}
              isLoading={isLoading}
              isInterrupted={isInterrupted}
              hitlToolNames={hitlToolNames}
              decisions={decisions}
              recordDecision={recordDecision}
              nestedInterrupts={nestedInterrupts}
              respond={respondToInterrupt}
              modelUnavailable={modelUnavailable}
              onRegenerate={handleRegenerate}
              error={error}
              rehydratedError={rehydratedError}
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

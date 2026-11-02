"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import {
  coerceMessageLikeToMessage,
  HumanMessage,
  isHumanMessage,
} from "@langchain/core/messages";
import type { BaseMessage, BaseMessageLike } from "@langchain/core/messages";
import { STREAM_CONTROLLER, useStream } from "@langchain/react";
import type { AnyStream, SubagentDiscoverySnapshot } from "@langchain/react";
import type { Interrupt } from "@langchain/langgraph-sdk";
import type { RunCompletedInfo } from "@langchain/langgraph-sdk/stream";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import type { Todo } from "@/components/ai-elements/todo-list";
import {
  type HitlDecision,
  type HitlResponse,
  useHitlApprovals,
} from "@/hooks/use-hitl-approvals";
import { useProtocolFetch } from "@/hooks/use-protocol-fetch";
import { useThrottledValue } from "@/hooks/use-throttled-value";
import * as artifactsApi from "@/lib/api/resources/artifacts";
import { protocolApiUrl } from "@/lib/api/protocol";
import * as threadsApi from "@/lib/api/resources/threads";
import {
  extractHitlToolNames,
  getToolStepState,
  pairToolCalls,
  splitInterrupts,
  type ToolCallView,
} from "@/lib/transcript";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useModelsStore } from "@/stores/models-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import type { Run } from "@/types/runs";
import type { ThreadRead } from "@/types/threads";

import { promptMessageToInput } from "./build-content";
import type { AttachmentReference } from "./build-content";
import { EMPTY_HELD, holdInterrupts } from "./interrupt-hold";
import { submitPendingAfterHydration } from "./pending-message";
import {
  initialSessionState,
  lastRunFailed,
  lastRunFallbackMessage,
  pickFailedRunError,
  sessionReducer,
  type SessionMeta,
} from "./session-reducer";

const EMPTY_TODOS: Todo[] = [];
/** Render cadence for the streamed views (tokens arrive far faster). */
const THROTTLE_MS = 60;
const STOP_SETTLE_POLL_MS = 100;
const STOP_SETTLE_TIMEOUT_MS = 10_000;
const snapshotMessages = (messages: BaseMessage[]): BaseMessage[] => [
  ...messages,
];

const wait = (ms: number) =>
  new Promise<void>((resolve) => {
    window.setTimeout(resolve, ms);
  });

/** Everything the session reaches the network through. Tests script it. */
export type ThreadSessionTransport = {
  /** What `useStream` talks to — the protocol endpoints. */
  fetch?: typeof fetch;
  readThread: (threadId: string) => Promise<ThreadRead>;
  listThreadRuns: (threadId: string) => Promise<Run[]>;
  getActiveRun?: (threadId: string) => Promise<Run | null>;
  retryFailedRun?: (threadId: string) => Promise<Run>;
  attachFile?: (
    threadId: string,
    file: Blob,
    filename: string,
  ) => Promise<AttachmentReference>;
  updateThreadModel?: (
    threadId: string,
    modelId: string,
    reasoningEffort?: string | null,
  ) => Promise<ThreadRead["thread"]>;
};

export const defaultTransport: ThreadSessionTransport = {
  readThread: threadsApi.readThread,
  listThreadRuns: threadsApi.listThreadRuns,
  getActiveRun: threadsApi.getActiveRun,
  retryFailedRun: threadsApi.retryFailedRun,
  attachFile: async (threadId, file, filename) => {
    const artifact = await artifactsApi.attachFile(threadId, file, filename);
    return {
      id: artifact.id,
      filename: artifact.filename,
      mediaType: artifact.mime_type,
    };
  },
  updateThreadModel: threadsApi.updateThreadModel,
};

export type ThreadSessionOptions = {
  threadId: string;
  agentId: string;
  transport?: ThreadSessionTransport;
  /** The approval the user addressed was already handled elsewhere. The
   * page decides what to do (today: reload the page). */
  onStaleInterrupt?: () => void;
  /** A run's active streaming phase ended. */
  onCompleted?: (info: RunCompletedInfo) => void;
  /** Cap on waiting for hydration before a parked first message is sent. */
  pendingMessageCapMs?: number;
};

export type ThreadSession = {
  meta: SessionMeta;
  /** Why opening failed, when `meta.status === "error"`. */
  openError: unknown;
  run: {
    status: "idle" | "streaming" | "interrupted";
    /** A submission is starting or the stream reports a run in flight. */
    isLoading: boolean;
    /** STOP was requested and the durable run has not been reconciled yet. */
    isStopping: boolean;
    /** The local submit started, but the server stream has not taken over yet. */
    isStarting: boolean;
    /** The stream stack's last error (command rejection or run failure). */
    error: unknown;
    /** Kept separately: the body renders the two differently. */
    rehydratedError: string | null;
    /** The latest durable run failed with replayable input. */
    canRetryInitial: boolean;
  };
  transcript: {
    messages: BaseMessage[];
    toolCalls: ToolCallView[];
    runs: Run[];
    subagents: ReadonlyMap<string, SubagentDiscoverySnapshot>;
    todos: Todo[];
    hydrated: boolean;
    hydrationError: unknown;
    /** Identity-stable handle for scoped subagent subscriptions. */
    stream: AnyStream;
  };
  hitl: {
    interrupt: Interrupt | null;
    nestedInterrupts: Interrupt[];
    hitlToolNames: Set<string> | null;
    pendingToolCalls: ToolCallView[];
    decisions: Record<string, HitlDecision>;
    recordDecision: (toolCallId: string, decision: HitlDecision) => void;
  };
  actions: {
    send: (
      message: PromptInputMessage,
      options?: { fileStorage?: boolean },
    ) => Promise<void>;
    regenerate: () => void;
    stop: () => void;
    respond: (
      response: HitlResponse,
      interruptId: string | null,
    ) => Promise<void>;
    loadLatestMessages: () => Promise<BaseMessage[]>;
    changeModel: (modelId: string) => Promise<void>;
    /** Pin a reasoning effort on the thread's current model for its next
     * runs; `null` = the model's default. */
    changeReasoningEffort: (effort: string | null) => Promise<void>;
    recheckModel: () => Promise<void>;
    /** Clear the mid-session sandbox gate so the composer comes back; the
     * page re-polls readiness alongside it. */
    recheckSandbox: () => void;
    /** Retry the protocol snapshot after its initial hydration failed. */
    rehydrate: () => Promise<void>;
    /** Replay the durable input of the latest failed run. */
    retryInitial: () => Promise<void>;
    /** Run the open sequence again after `meta.status === "error"`. A parked
     * first message is still parked — it is consumed only once the thread
     * metadata has loaded. */
    reopen: () => void;
  };
};

/**
 * One thread, as the chat page sees it: what it is doing and what may be done
 * to it. Wraps `useStream` (which owns hydration, reattach and the live
 * projections) with the thread metadata read, the failed-run error
 * rehydration, the HITL batch, the active-run bookkeeping and the parked
 * first message. The ordering rules live in the pure modules next to this
 * file; the page renders the result.
 */
export function useThreadSession({
  threadId,
  agentId,
  transport = defaultTransport,
  onStaleInterrupt,
  onCompleted,
  pendingMessageCapMs,
}: ThreadSessionOptions): ThreadSession {
  const [state, dispatch] = useReducer(sessionReducer, initialSessionState);
  const [durableRunActivity, setDurableRunActivity] = useState<{
    threadId: string;
    active: boolean;
    retryable: boolean;
  } | null>(null);
  const [runHistory, setRunHistory] = useState<{
    threadId: string;
    runs: Run[];
  } | null>(null);
  const runActivityGeneration = useRef(0);
  const retryStartingThread = useRef<string | null>(null);
  const submissionSequence = useRef(0);
  const sendingThread = useRef<string | null>(null);
  const pendingRunStarts = useRef(
    new Map<
      string,
      {
        sequence: number;
        accepted: boolean;
        resolve: (accepted: boolean) => void;
      }
    >(),
  );
  const [pendingSubmission, setPendingSubmission] = useState<{
    threadId: string;
    sequence: number;
    baselineUserMessageCount: number;
    accepted: boolean;
  } | null>(null);
  const [submittedUserFallback, setSubmittedUserFallback] = useState<{
    threadId: string;
    message: HumanMessage;
  } | null>(null);
  const currentThreadId = useRef(threadId);
  currentThreadId.current = threadId;
  const models = useModelsStore((store) => store.models);

  const callbacks = useRef({ onStaleInterrupt, onCompleted });
  useEffect(() => {
    callbacks.current = { onStaleInterrupt, onCompleted };
  });

  const settleRunStart = useCallback(
    (forThread: string, accepted: boolean) => {
      const pending = pendingRunStarts.current.get(forThread);
      if (pending != null) {
        pending.accepted = accepted;
        pendingRunStarts.current.delete(forThread);
        pending.resolve(accepted);
      }
      if (accepted && currentThreadId.current === forThread) {
        runActivityGeneration.current += 1;
        setPendingSubmission((current) =>
          current?.threadId === forThread
            ? { ...current, accepted: true }
            : current,
        );
        setDurableRunActivity({
          threadId: forThread,
          active: true,
          retryable: false,
        });
        useActiveRunsStore.getState().markThreadRunning(forThread);
      }
    },
    [],
  );

  const readRunActivity = useCallback(async () => {
    if (transport.getActiveRun) {
      const active = await transport.getActiveRun(threadId);
      if (active != null) {
        return { active: true, retryable: false };
      }
    }
    const runs = await transport.listThreadRuns(threadId);
    const latest = runs[0];
    return {
      active: latest?.status === "pending" || latest?.status === "running",
      retryable: latest?.status === "error" || latest?.status === "timeout",
    };
  }, [threadId, transport]);

  const protocolFetch = useProtocolFetch(threadId, {
    baseFetch: transport.fetch,
    onModelUnavailable: (forThread) => {
      dispatch({ type: "model-unavailable", threadId: forThread });
    },
    onSandboxUnavailable: (forThread, detail) => {
      dispatch({ type: "sandbox-unavailable", threadId: forThread, detail });
    },
    onStaleInterrupt: (forThread) => {
      // A late 409 for the thread the page left must not reload this one.
      if (forThread !== threadId) return;
      callbacks.current.onStaleInterrupt?.();
    },
    onRunStartSettled: (forThread, accepted) => {
      settleRunStart(forThread, accepted);
    },
  });

  // The SDK's hydration reads (`getState`, `getHistory`) go through the
  // client's own caller, not `fetch`; hand both the same transport so every
  // protocol request shares the same-origin guard and the session cookie.
  // Memoized: the SDK rebuilds its client (and controller) on identity change.
  const callerOptions = useMemo(
    () => ({ fetch: protocolFetch, maxRetries: 0 }),
    [protocolFetch],
  );
  const completionStream = useRef<AnyStream | null>(null);

  const stream = useStream({
    assistantId: agentId,
    apiUrl: protocolApiUrl(),
    threadId,
    messagesKey: "messages",
    fetch: protocolFetch,
    callerOptions,
    onCreated: () => {
      settleRunStart(threadId, true);
    },
    onCompleted: (info) => {
      const generation = ++runActivityGeneration.current;
      // A terminal replay can race a newly accepted run. The SDK associates
      // that terminal with the new run id, so never declare the thread idle
      // until the durable run table agrees.
      void readRunActivity()
        .then((activity) => {
          if (
            currentThreadId.current === threadId &&
            generation === runActivityGeneration.current
          ) {
            setDurableRunActivity({ threadId, ...activity });
          }
        })
        .catch(() => {
          // Keep the active state and its polling loop until reconciliation
          // succeeds; clearing it here would reintroduce the missing spinner.
        });
      useActiveRunsStore.getState().requestPoll();
      void transport
        .listThreadRuns(threadId)
        .then((runs) => {
          if (currentThreadId.current === threadId) {
            setRunHistory({ threadId, runs });
          }
        })
        .catch(() => {});
      callbacks.current.onCompleted?.(info);
      if (info.runId == null) {
        queueMicrotask(() => {
          if (currentThreadId.current !== threadId) return;
          const controller = completionStream.current?.[STREAM_CONTROLLER];
          if (controller) void controller.hydrate(threadId);
        });
      }
    },
  });

  // `stream` is a new object every tick. Keep selector identity stable for
  // one controller, but switch it when the SDK replaces that controller
  // during an in-place thread transition.
  const streamController = stream[STREAM_CONTROLLER];
  const selectorStream = useMemo(
    () => stream as AnyStream,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [streamController],
  );
  useEffect(() => {
    completionStream.current = selectorStream;
    return () => {
      if (completionStream.current === selectorStream) {
        completionStream.current = null;
      }
    };
  }, [selectorStream]);
  // …but `hydrationPromise` is replaced by the SDK on every (re)hydrate, so
  // waiting on it must read the latest rendered stream, not the handle.
  const latestStream = useRef(stream);
  useEffect(() => {
    latestStream.current = stream;
  }, [stream]);
  const [hydratedThreadId, setHydratedThreadId] = useState<string | null>(null);
  const [hydrationFailure, setHydrationFailure] = useState<{
    threadId: string;
    error: unknown;
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void latestStream.current.hydrationPromise.then(
      () => {
        if (cancelled) return;
        setHydratedThreadId(threadId);
        setHydrationFailure(null);
      },
      (error: unknown) => {
        if (!cancelled) setHydrationFailure({ threadId, error });
      },
    );
    return () => {
      cancelled = true;
    };
  }, [threadId]);
  const [dismissedStreamError, setDismissedStreamError] = useState<{
    threadId: string;
    error: unknown;
  } | null>(null);
  const durableRunActive =
    durableRunActivity?.threadId === threadId && durableRunActivity.active;
  const durableRunRetryable =
    durableRunActivity?.threadId === threadId && durableRunActivity.retryable;
  const durableRunChecking = durableRunActivity?.threadId !== threadId;

  useEffect(() => {
    if (!durableRunActive) return;
    let cancelled = false;
    const refresh = async () => {
      const generation = runActivityGeneration.current;
      const activity = await readRunActivity();
      if (
        !cancelled &&
        generation === runActivityGeneration.current &&
        retryStartingThread.current !== threadId
      ) {
        setDurableRunActivity({ threadId, ...activity });
      }
    };
    const timer = window.setInterval(() => {
      void refresh().catch(() => {});
    }, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [durableRunActive, readRunActivity, threadId]);

  // --- interrupts: hold identity while the set is unchanged ----------------
  const [held, setHeld] = useState(EMPTY_HELD);
  const nextHeld = holdInterrupts(held, stream.interrupts);
  if (nextHeld !== held) setHeld(nextHeld);
  const { root: interrupt, nested: nestedInterrupts } = useMemo(
    () => splitInterrupts(held.list),
    [held],
  );
  const isInterrupted = interrupt != null;
  const hitlToolNames = useMemo(
    () => extractHitlToolNames(interrupt?.value),
    [interrupt],
  );

  // --- transcript views -----------------------------------------------------
  const streamedMessages = useThrottledValue(stream.messages, THROTTLE_MS, {
    // `message-finish` can enrich an existing message with usage metadata
    // without replacing the messages array. The stream object still ticks
    // for that SSE event; snapshot only at the throttled render cadence.
    revision: stream,
    snapshot: snapshotMessages,
  });
  const messages = useMemo(() => {
    if (submittedUserFallback?.threadId !== threadId) return streamedMessages;
    const fallback = submittedUserFallback.message;
    const index = streamedMessages.findIndex(
      (message) => message.id === fallback.id,
    );
    if (index < 0) return [...streamedMessages, fallback];

    const current = streamedMessages[index];
    const displayText = current.additional_kwargs?.display_text;
    if (
      current.text.length > 0 ||
      (typeof displayText === "string" && displayText.length > 0)
    ) {
      return streamedMessages;
    }

    // The protocol echoes a human message as start/block/finish events. If
    // rendering lands between start and block, the SDK briefly replaces the
    // optimistic message with an empty one. Keep the submitted copy until
    // the content event catches up so the user's bubble cannot disappear.
    const next = streamedMessages.slice();
    next[index] = fallback;
    return next;
  }, [streamedMessages, submittedUserFallback, threadId]);
  const liveToolCalls = useThrottledValue(stream.toolCalls, THROTTLE_MS);
  const [stoppingThreadId, setStoppingThreadId] = useState<string | null>(null);
  const stoppingRef = useRef<string | null>(null);
  const stopSequence = useRef(0);
  const isStopping = stoppingThreadId === threadId;
  const toolCalls = useMemo(() => {
    const paired = pairToolCalls(messages, liveToolCalls);
    // Events already in flight can arrive after STOP. Do not let those
    // transient handles leave a tool spinner behind while server state
    // is converging; the authoritative rehydrate below restores anything
    // that genuinely belongs to a following queued run.
    return isStopping
      ? paired.filter((toolCall) => toolCall.status !== "running")
      : paired;
  }, [isStopping, messages, liveToolCalls]);
  const todos =
    ((stream.values as Record<string, unknown>).todos as Todo[] | undefined) ??
    EMPTY_TODOS;
  const submissionPending = pendingSubmission?.threadId === threadId;
  const renderedUserMessageCount = messages.filter(
    (message) => isHumanMessage(message) && message.name !== "host",
  ).length;
  useEffect(() => {
    if (
      !stream.isLoading &&
      durableRunActivity?.threadId === threadId &&
      !durableRunActivity.active
    ) {
      setPendingSubmission((current) =>
        current?.threadId === threadId && current.accepted ? null : current,
      );
    }
  }, [durableRunActivity, stream.isLoading, threadId]);
  const submissionStarting =
    submissionPending &&
    renderedUserMessageCount <= pendingSubmission.baselineUserMessageCount;

  // --- actions ----------------------------------------------------------------
  const userActed = useCallback(() => {
    dispatch({ type: "user-acted" });
    if (stream.error != null) {
      setDismissedStreamError({ threadId, error: stream.error });
    }
  }, [stream.error, threadId]);

  const send = useCallback(
    async (
      message: PromptInputMessage,
      options?: { fileStorage?: boolean },
    ) => {
      if (stoppingRef.current === threadId) {
        throw new DOMException(
          "Conversation changed before sending",
          "AbortError",
        );
      }
      if (!message.text?.trim() && (message.files?.length ?? 0) === 0) return;
      if (sendingThread.current === threadId) {
        throw new DOMException(
          "A message is already being sent",
          "InvalidStateError",
        );
      }
      sendingThread.current = threadId;
      // Once `submit` is in flight, its own `finally` owns the send lock.
      let released = false;
      try {
        userActed();
        const vision =
          models.find((model) => model.id === state.meta.thread?.modelId)
            ?.multimodal !== false;
        const input = await promptMessageToInput(message, {
          vision,
          upload:
            options?.fileStorage === false
              ? undefined
              : async (file) => {
                  const blob = await (await fetch(file.url)).blob();
                  return await (
                    transport.attachFile ?? defaultTransport.attachFile!
                  )(threadId, blob, file.filename || "file");
                },
        });
        if (input == null || currentThreadId.current !== threadId) {
          throw new DOMException(
            "Conversation changed before sending",
            "AbortError",
          );
        }
        const sequence = ++submissionSequence.current;
        let settleRunStart!: (accepted: boolean) => void;
        const runStartSettled = new Promise<boolean>((resolve) => {
          settleRunStart = resolve;
        });
        const pendingStart = {
          sequence,
          accepted: false,
          resolve: settleRunStart,
        };
        pendingRunStarts.current.set(threadId, pendingStart);
        setPendingSubmission({
          threadId,
          sequence,
          baselineUserMessageCount: renderedUserMessageCount,
          accepted: false,
        });
        const additional_kwargs = {
          ...(input.attachments.length > 0
            ? {
                attachments: input.attachments.map((attachment) => ({
                  id: attachment.id,
                  filename: attachment.filename,
                  media_type: attachment.mediaType,
                })),
              }
            : {}),
          ...(Array.isArray(input.content)
            ? { display_text: input.displayText }
            : {}),
          ...(input.inlineTextFiles.length > 0
            ? {
                inline_text_files: input.inlineTextFiles.map((file) => ({
                  block_index: file.blockIndex,
                  filename: file.filename,
                  media_type: file.mediaType,
                })),
              }
            : {}),
        };
        const messageId = globalThis.crypto.randomUUID();
        const submittedMessage = new HumanMessage({
          id: messageId,
          content: input.content as HumanMessage["content"],
          additional_kwargs,
        });
        setSubmittedUserFallback({
          threadId,
          message: submittedMessage,
        });
        let submissionError: unknown;
        // `submit` settles only once the run has *ended*. The composer must
        // not wait that long: while it does, its submit guards stay held and
        // every later prompt is dropped instead of being queued. So the
        // promise returned here settles as soon as the server has durably
        // accepted the run; the run itself is watched in the background and
        // the send lock is released only when it ends (a second direct
        // `submit` on an active run would roll it back).
        const submission = streamController
          .submit(
            {
              messages: [
                {
                  type: "human",
                  id: messageId,
                  content: input.content,
                  ...(Object.keys(additional_kwargs).length > 0
                    ? { additional_kwargs }
                    : {}),
                },
              ],
            },
            {
              onError: (error) => {
                submissionError = error;
              },
            },
          )
          .finally(() => {
            if (pendingRunStarts.current.get(threadId) === pendingStart) {
              pendingRunStarts.current.delete(threadId);
              pendingStart.resolve(false);
            }
            if (!pendingStart.accepted) {
              setPendingSubmission((current) =>
                current?.threadId === threadId && current.sequence === sequence
                  ? null
                  : current,
              );
              setSubmittedUserFallback((current) =>
                current?.threadId === threadId &&
                current.message.id === messageId
                  ? null
                  : current,
              );
            }
            if (sendingThread.current === threadId) {
              sendingThread.current = null;
            }
          });
        released = true;
        const first = await Promise.race([
          runStartSettled.then((accepted) => ({
            type: "start" as const,
            accepted,
          })),
          submission.then(
            () => ({ type: "ended" as const }),
            (error: unknown) => ({ type: "rejected" as const, error }),
          ),
        ]);
        if (first.type === "rejected") throw first.error;
        if (first.type === "start" && first.accepted) {
          if (currentThreadId.current !== threadId) {
            throw new DOMException(
              "Conversation changed before sending",
              "AbortError",
            );
          }
          return;
        }
        // The run never started (rejected `run.start`) or ended before the
        // start settled: wait for the submit to surface its error.
        await submission;
        if (currentThreadId.current !== threadId) {
          throw new DOMException(
            "Conversation changed before sending",
            "AbortError",
          );
        }
        if (submissionError !== undefined && !(await runStartSettled)) {
          throw submissionError;
        }
      } finally {
        if (!released && sendingThread.current === threadId) {
          sendingThread.current = null;
        }
      }
    },
    [
      models,
      renderedUserMessageCount,
      state.meta.thread?.modelId,
      streamController,
      threadId,
      transport,
      userActed,
    ],
  );

  const regenerate = useCallback(() => {
    if (stoppingRef.current === threadId) return;
    if (!messages.some(isHumanMessage)) return;
    userActed();
    void streamController
      .submit(null, {
        config: { configurable: { trigger: "regenerate-message" } },
      })
      .catch((error: unknown) => {
        console.error("Could not regenerate the response:", error);
      });
  }, [messages, streamController, threadId, userActed]);

  const stop = useCallback(() => {
    if (stoppingRef.current === threadId) return;
    stoppingRef.current = threadId;
    setStoppingThreadId(threadId);
    const sequence = ++stopSequence.current;
    useActiveRunsStore.getState().requestPoll();

    // Capture the run that is active before STOP. A queued run may become
    // active immediately after it, so polling "the active run" afterwards
    // could wait for the wrong turn.
    const activeRun = transport.listThreadRuns(threadId).then(
      (runs) => runs.find((run) => run.status === "running") ?? null,
      () => null,
    );

    void (async () => {
      try {
        await streamController.stop();
        const stoppedRun = await activeRun;
        if (stoppedRun != null) {
          const deadline = Date.now() + STOP_SETTLE_TIMEOUT_MS;
          while (
            stopSequence.current === sequence &&
            currentThreadId.current === threadId &&
            Date.now() < deadline
          ) {
            const runs = await transport
              .listThreadRuns(threadId)
              .catch(() => []);
            const current = runs.find((run) => run.id === stoppedRun.id);
            if (
              current == null ||
              (current.status !== "pending" && current.status !== "running")
            ) {
              break;
            }
            await wait(STOP_SETTLE_POLL_MS);
          }
        }

        if (
          stopSequence.current === sequence &&
          currentThreadId.current === threadId
        ) {
          // stop() preserves the SDK's projections, including partial
          // tool handles. Swap away and back to discard that transient
          // stream state and rebuild from the durable checkpoint.
          await streamController.hydrate(null);
          const hydration = streamController.hydrate(currentThreadId.current);
          const hydrationPromise = streamController.hydrationPromise;
          await Promise.all([hydration, hydrationPromise]);
        }
      } catch (error) {
        console.error("Could not synchronize the stopped run:", error);
      } finally {
        useActiveRunsStore.getState().requestPoll();
        if (stopSequence.current === sequence) {
          stoppingRef.current = null;
          setStoppingThreadId((current) =>
            current === threadId ? null : current,
          );
        }
      }
    })();
  }, [streamController, threadId, transport]);

  const respond = useCallback(
    async (response: HitlResponse, addressedId: string | null) => {
      if (stoppingRef.current === threadId) return;
      userActed();
      await streamController.respond(
        response,
        addressedId != null ? { interruptId: addressedId } : undefined,
      );
    },
    [streamController, threadId, userActed],
  );

  const loadLatestMessages = useCallback(async () => {
    const snapshot = await stream.client.threads.getState<{
      messages?: BaseMessageLike[];
    }>(threadId);
    return (snapshot.values.messages ?? []).map(coerceMessageLikeToMessage);
  }, [stream.client, threadId]);

  const recheckSandbox = useCallback(() => {
    dispatch({ type: "sandbox-rechecked", threadId });
  }, [threadId]);

  const rehydrate = useCallback(async () => {
    setHydratedThreadId(null);
    setHydrationFailure(null);
    try {
      await streamController.hydrate(null);
      // hydrate() records fetch failures on the controller and resolves;
      // hydrationPromise is the rejection channel for that cycle.
      const hydration = streamController.hydrate(threadId);
      const hydrationPromise = streamController.hydrationPromise;
      await Promise.all([hydration, hydrationPromise]);
      if (currentThreadId.current === threadId) {
        setHydratedThreadId(threadId);
      }
    } catch (error) {
      if (currentThreadId.current === threadId) {
        setHydrationFailure({ threadId, error });
      }
      throw error;
    }
  }, [streamController, threadId]);

  const retryInitial = useCallback(async () => {
    userActed();
    retryStartingThread.current = threadId;
    runActivityGeneration.current += 1;
    setDurableRunActivity({ threadId, active: true, retryable: false });
    let started = false;
    try {
      await (transport.retryFailedRun ?? defaultTransport.retryFailedRun!)(
        threadId,
      );
      started = true;
      runActivityGeneration.current += 1;
      retryStartingThread.current = null;
      setDurableRunActivity({
        threadId,
        active: true,
        retryable: false,
      });
      useActiveRunsStore.getState().markThreadRunning(threadId);
      // The retry starts outside StreamController.submit(). Rehydrate so
      // an idle controller opens its deferred event pump for this run.
      await rehydrate();
    } catch (error) {
      if (!started) {
        runActivityGeneration.current += 1;
        retryStartingThread.current = null;
        if (currentThreadId.current === threadId) {
          setDurableRunActivity({
            threadId,
            active: false,
            retryable: true,
          });
        }
        throw error;
      }
      // The run exists; rehydrate() already exposed its own retryable
      // history error. Keep activity polling until it settles.
    }
  }, [rehydrate, threadId, transport, userActed]);

  const changeModel = useCallback(
    async (modelId: string) => {
      const thread = await (
        transport.updateThreadModel ?? threadsApi.updateThreadModel
      )(threadId, modelId);
      dispatch({ type: "thread-updated", threadId, thread });
    },
    [threadId, transport],
  );

  const currentModelId = state.meta.thread?.modelId;
  const changeReasoningEffort = useCallback(
    async (effort: string | null) => {
      if (!currentModelId) return;
      const thread = await (
        transport.updateThreadModel ?? threadsApi.updateThreadModel
      )(threadId, currentModelId, effort);
      dispatch({ type: "thread-updated", threadId, thread });
    },
    [currentModelId, threadId, transport],
  );

  const recheckModel = useCallback(async () => {
    const forThread = threadId;
    try {
      const { thread } = await transport.readThread(forThread);
      dispatch({
        type: "thread-updated",
        threadId: forThread,
        thread,
      });
    } catch {
      // Leave the banner as it is; the user can try again.
    }
  }, [transport, threadId]);

  // --- HITL batch -------------------------------------------------------------
  const pendingToolCalls = useMemo(
    () =>
      toolCalls.filter(
        (tc) =>
          getToolStepState(tc, isInterrupted, hitlToolNames) ===
          "awaiting-approval",
      ),
    [toolCalls, isInterrupted, hitlToolNames],
  );
  const pendingIdsAreReal = pendingToolCalls.every((tc) => tc.callId != null);
  const { decisions, recordDecision } = useHitlApprovals({
    interruptId: pendingIdsAreReal ? (interrupt?.id ?? null) : null,
    pendingToolCalls,
    respond,
  });

  // --- open the thread ------------------------------------------------------
  const consumePendingMessage = usePendingMessageStore(
    (s) => s.consumePendingMessage,
  );
  const setPendingMessage = usePendingMessageStore((s) => s.setPendingMessage);
  const [openAttempt, setOpenAttempt] = useState(0);
  const reopen = useCallback(() => {
    setOpenAttempt((n) => n + 1);
  }, []);
  useEffect(() => {
    // A newer attempt (thread switch or Retry) cancels this one's effects:
    // its responses are dropped rather than landing on the newer state.
    let cancelled = false;
    // The parked message this attempt has taken out of the store and not yet
    // sent. Handed back in the cleanup — synchronously, before a newer
    // attempt's effect body runs — so the newer attempt finds it.
    let claimed: PromptInputMessage | null = null;
    dispatch({ type: "opened", threadId });
    const activityGeneration = ++runActivityGeneration.current;
    retryStartingThread.current = null;
    setDurableRunActivity(null);

    const open = async () => {
      const read = await transport.readThread(threadId);
      if (cancelled) return;
      dispatch({ type: "thread-loaded", threadId, read });
      const runs = await transport.listThreadRuns(threadId);
      const latest = runs[0];
      const activity = {
        active: latest?.status === "pending" || latest?.status === "running",
        retryable:
          latest?.status === "error" || latest?.status === "timeout",
      };
      if (cancelled || activityGeneration !== runActivityGeneration.current) {
        return;
      }
      setRunHistory({ threadId, runs });
      setDurableRunActivity({ threadId, ...activity });

      const pending = consumePendingMessage(threadId);
      if (pending) {
        claimed = pending;
        await submitPendingAfterHydration(
          latestStream.current.hydrationPromise,
          async () => {
            // Cancelled while waiting: the cleanup has already parked
            // the message again; sending it here would reach a stream
            // nobody is watching.
            if (cancelled) return;
            await send(pending);
            claimed = null;
          },
          { capMs: pendingMessageCapMs },
        );
        return;
      }

      if (lastRunFailed(read.thread)) {
        const fallback = lastRunFallbackMessage(read.thread);
        const error = await transport
          .listThreadRuns(threadId)
          .then((runs) => pickFailedRunError(runs, fallback))
          .catch(() => fallback);
        if (cancelled) return;
        dispatch({ type: "last-run-error-loaded", threadId, error });
      }
    };
    open().catch((error: unknown) => {
      if (cancelled) return;
      if (claimed) {
        setPendingMessage(threadId, claimed);
        claimed = null;
      }
      console.error("Could not open the thread:", error);
      dispatch({ type: "open-failed", threadId, error });
    });
    return () => {
      cancelled = true;
      if (claimed) {
        setPendingMessage(threadId, claimed);
        claimed = null;
      }
    };
    // The open sequence runs once per thread (and per explicit reopen); the
    // callbacks it uses are stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [threadId, openAttempt]);

  const runStatus: ThreadSession["run"]["status"] = isInterrupted
    ? "interrupted"
    : stream.isLoading ||
        durableRunActive ||
        durableRunChecking ||
        submissionPending ||
        isStopping
      ? "streaming"
      : "idle";
  const visibleStreamError =
    dismissedStreamError?.threadId === threadId &&
    Object.is(dismissedStreamError.error, stream.error)
      ? null
      : stream.error;

  return {
    meta: state.meta,
    openError: state.openError,
    run: {
      status: runStatus,
      isLoading:
        stream.isLoading ||
        durableRunActive ||
        durableRunChecking ||
        submissionPending ||
        isStopping,
      isStopping,
      isStarting: submissionStarting,
      error: visibleStreamError,
      rehydratedError: state.rehydratedError,
      canRetryInitial:
        durableRunActivity?.threadId === threadId
          ? durableRunRetryable
          : state.meta.thread?.lastRunStatus === "error" ||
            state.meta.thread?.lastRunStatus === "timeout",
    },
    transcript: {
      messages,
      toolCalls,
      runs: runHistory?.threadId === threadId ? runHistory.runs : [],
      subagents: stream.subagents,
      todos,
      hydrated: hydratedThreadId === threadId,
      hydrationError:
        hydrationFailure?.threadId === threadId ? hydrationFailure.error : null,
      stream: selectorStream,
    },
    hitl: {
      interrupt,
      nestedInterrupts,
      hitlToolNames,
      pendingToolCalls,
      decisions,
      recordDecision,
    },
    actions: {
      send,
      regenerate,
      stop,
      respond,
      loadLatestMessages,
      changeModel,
      changeReasoningEffort,
      recheckModel,
      recheckSandbox,
      rehydrate,
      retryInitial,
      reopen,
    },
  };
}

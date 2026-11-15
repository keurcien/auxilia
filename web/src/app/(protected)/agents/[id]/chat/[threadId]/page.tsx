"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { BaseMessage } from "@langchain/core/messages";
import { isAIMessage, isHumanMessage } from "@langchain/core/messages";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import ChatPromptInput from "../components/prompt-input";
import {
  AlertTriangle,
  ArchiveIcon,
  Brain,
  ChevronRight,
  CircleCheck,
  CircleSlash,
  LoaderCircle,
  Mail,
  MailOpen,
  ShieldCheck,
  Undo2,
} from "lucide-react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { toast } from "sonner";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { chatHeaderFromThread, useThreadSession } from "@/lib/thread-session";
import * as threadsApi from "@/lib/api/resources/threads";
import { getApiErrorMessage } from "@/lib/api/errors";
import { getThreadCost } from "@/lib/api/resources/thread-costs";
import { isResponseSoundEnabled } from "@/lib/user-preferences";
import { ConversationBody } from "./conversation-body";
import { usePromptQueue } from "@/hooks/use-prompt-queue";
import { ThreadMap } from "@/components/ai-elements/thread-map";
import { ShareConversation } from "./share-conversation";
import type { Thread, ThreadResourceSettings } from "@/types/threads";
import type { QueuedPrompt } from "@/types/runs";
import { ArtifactWorkspace } from "@/components/artifacts/workspace";
import { isElicitation } from "@/lib/transcript";
import { useThreadsStore } from "@/stores/threads-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useWorkspaceEventsStore } from "@/stores/workspace-events-store";
import {
  ChatHeaderActions,
  ChatHeaderLeadingActions,
  ChatMemoryToggle,
  ChatMobileActionsSheet,
  ChatMobileNotificationsSection,
  ChatNotificationsToggle,
} from "@/components/layout/chat-header";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Switch } from "@/components/ui/switch";

const EMPTY_RESOURCE_SETTINGS: ThreadResourceSettings = {
  toolMode: null,
  disabledMcpServerIds: [],
  disabledSkillIds: [],
  disabledSandboxIds: [],
  disabledSubagentIds: [],
};

/**
 * The chat page renders one thread session. Run state, HITL, hydration and
 * the failed-run error all come from `useThreadSession`; this file owns only
 * what is visual — the banners, the composer and the header sync.
 */
const ChatPage = () => {
  const params = useParams();
  const agentId = params.id as string;
  const threadId = params.threadId as string;
  const completionSequence = useRef(0);
  const playedCompletionSequence = useRef(0);
  const completionCandidate = useRef(0);
  const completionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const readStateInFlight = useRef(false);
  const automaticReadPromise = useRef<Promise<void> | null>(null);
  const readCompletionSequence = useRef(0);
  const runStatusRef = useRef<"idle" | "streaming" | "interrupted">("idle");
  const transcriptMessages = useRef<BaseMessage[]>([]);
  // Id of the assistant message whose completion was already accounted for.
  // Set when the user starts a run (the response on screen at that moment is
  // old news) and when a completion is recorded, so a replayed terminal event
  // for that same response can never be mistaken for a fresh one.
  const acknowledgedAssistantId = useRef<string | null>(null);
  const [successfulCompletion, setSuccessfulCompletion] = useState<{
    threadId: string;
    sequence: number;
  } | null>(null);
  const [responsePendingDisplay, setResponsePendingDisplay] = useState<
    string | null
  >(null);
  const [pageVisible, setPageVisible] = useState(false);
  const [resourceSettingsOverride, setResourceSettingsOverride] = useState<{
    threadId: string;
    settings: ThreadResourceSettings;
  } | null>(null);
  const [resourceSettingsSaving, setResourceSettingsSaving] = useState(false);
  const [memoryOverride, setMemoryOverride] = useState<{
    threadId: string;
    enabled: boolean;
  } | null>(null);
  const [memorySaving, setMemorySaving] = useState(false);
  // Optimistic values hold only until the next server read of the thread, so
  // a change made from another tab is never masked by a stale local choice.
  const [completionOverride, setCompletionOverride] = useState<{
    thread: Thread | null;
    completed: boolean;
  } | null>(null);
  const [completionSaving, setCompletionSaving] = useState(false);
  const [readOverride, setReadOverride] = useState<{
    thread: Thread | null;
    isUnread: boolean;
  } | null>(null);
  const [readSaving, setReadSaving] = useState(false);
  const manuallyUnreadOnPage = useRef(false);
  const threadsVersion = useWorkspaceEventsStore(
    (state) => state.threadsVersion,
  );
  const projectsVersion = useWorkspaceEventsStore(
    (state) => state.projectsVersion,
  );
  const setThreadCompleted = useThreadsStore(
    (state) => state.setThreadCompleted,
  );
  const setThreadReadState = useThreadsStore(
    (state) => state.setThreadReadState,
  );
  const refreshThreads = useThreadsStore((state) => state.refreshThreads);
  const refreshProjectTree = useProjectsStore((state) => state.refreshTree);

  const acknowledgeCurrentResponse = () => {
    acknowledgedAssistantId.current =
      transcriptMessages.current.findLast(isAIMessage)?.id ?? null;
  };

  const settleSuccessfulCompletion = (candidate: number, attempt = 0) => {
    if (completionTimer.current !== null) {
      clearTimeout(completionTimer.current);
    }
    completionTimer.current = setTimeout(() => {
      if (candidate !== completionCandidate.current) return;
      // The run status and rendered transcript settle on separate React
      // updates. Wait for both instead of judging a terminal event against
      // the throttled transcript from the preceding render.
      if (runStatusRef.current !== "idle") {
        if (attempt < 50) settleSuccessfulCompletion(candidate, attempt + 1);
        return;
      }
      const messages = transcriptMessages.current;
      const latestUserPrompt = messages.findLastIndex(
        (message) => isHumanMessage(message) && message.name !== "host",
      );
      const latestAssistantResponse = messages.findLastIndex(isAIMessage);
      if (latestAssistantResponse <= latestUserPrompt) {
        if (attempt < 10) settleSuccessfulCompletion(candidate, attempt + 1);
        return;
      }
      const assistantId = messages.at(latestAssistantResponse)?.id ?? null;
      if (
        assistantId !== null &&
        assistantId === acknowledgedAssistantId.current
      ) {
        setResponsePendingDisplay(null);
        return;
      }
      acknowledgedAssistantId.current = assistantId;
      setResponsePendingDisplay(null);
      completionSequence.current += 1;
      setSuccessfulCompletion({
        threadId,
        sequence: completionSequence.current,
      });
    }, 80);
  };

  const { meta, openError, run, transcript, hitl, actions } = useThreadSession({
    threadId,
    agentId,
    onStaleInterrupt: () => {
      window.location.reload();
    },
    onCompleted: ({ reason }) => {
      const candidate = ++completionCandidate.current;
      if (reason !== "success") {
        setResponsePendingDisplay(null);
        if (completionTimer.current !== null)
          clearTimeout(completionTimer.current);
        return;
      }
      setResponsePendingDisplay(threadId);
      settleSuccessfulCompletion(candidate);
    },
  });
  const recheckThreadMetadata = actions.recheckModel;
  const syncLatestThread = actions.syncLatest;
  useEffect(() => {
    if (
      (threadsVersion === 0 && projectsVersion === 0) ||
      meta.status !== "ready"
    ) {
      return;
    }
    void recheckThreadMetadata();
  }, [meta.status, projectsVersion, recheckThreadMetadata, threadsVersion]);
  useEffect(() => {
    let wasAway = document.visibilityState === "hidden";
    let syncing = false;
    let cancelled = false;
    let retryUsed = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const synchronize = () => {
      if (
        cancelled ||
        syncing ||
        !wasAway ||
        document.visibilityState !== "visible"
      ) {
        return;
      }
      wasAway = false;
      syncing = true;
      void syncLatestThread()
        .then(() => {
          retryUsed = false;
        })
        .catch((error: unknown) => {
          console.error("Could not synchronize the resumed thread:", error);
          if (!cancelled && !retryUsed) {
            retryUsed = true;
            retryTimer = setTimeout(() => {
              wasAway = true;
              synchronize();
            }, 1_500);
          }
        })
        .finally(() => {
          syncing = false;
        });
    };

    const updateVisibility = () => {
      const visible = document.visibilityState === "visible";
      setPageVisible(visible);
      if (!visible) {
        wasAway = true;
        retryUsed = false;
        return;
      }
      synchronize();
    };
    const handlePageShow = (event: PageTransitionEvent) => {
      if (event.persisted) wasAway = true;
      synchronize();
    };
    const handleOnline = () => {
      wasAway = true;
      retryUsed = false;
      synchronize();
    };

    updateVisibility();
    document.addEventListener("visibilitychange", updateVisibility);
    window.addEventListener("pageshow", handlePageShow);
    window.addEventListener("online", handleOnline);
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      document.removeEventListener("visibilitychange", updateVisibility);
      window.removeEventListener("pageshow", handlePageShow);
      window.removeEventListener("online", handleOnline);
    };
  }, [syncLatestThread, threadId]);
  useEffect(() => {
    transcriptMessages.current = transcript.messages;
  }, [transcript.messages]);
  const [scrolledThreadId, setScrolledThreadId] = useState<string | null>(
    null,
  );
  const transcriptShown =
    transcript.hydrated && transcript.messages.length > 0;
  useEffect(() => {
    if (transcriptShown) setScrolledThreadId(threadId);
  }, [threadId, transcriptShown]);
  useEffect(() => {
    runStatusRef.current = run.status;
  }, [run.status]);
  useEffect(
    () => () => {
      completionCandidate.current += 1;
      if (completionTimer.current !== null)
        clearTimeout(completionTimer.current);
    },
    [threadId],
  );
  const userMessageCount = transcript.messages.filter(
    (message) => isHumanMessage(message) && message.name !== "host",
  ).length;
  const initialOptimisticMessage = usePendingMessageStore(
    (store) => store.optimisticMessages.get(threadId) ?? null,
  );
  const clearOptimisticMessage = usePendingMessageStore(
    (store) => store.clearOptimisticMessage,
  );
  useEffect(() => {
    if (userMessageCount > 0) clearOptimisticMessage(threadId);
  }, [clearOptimisticMessage, threadId, userMessageCount]);
  const initialPromptRunActive = transcript.runs.some(
    (item) =>
      item.kind === "prompt" &&
      (item.status === "pending" || item.status === "running"),
  );
  const initialOptimisticPrompt = useMemo<QueuedPrompt | null>(() => {
    if (userMessageCount > 0) return null;
    const text =
      initialOptimisticMessage?.text?.trim() ||
      (initialPromptRunActive
        ? (meta.thread?.firstMessageContent?.trim() ?? "")
        : "");
    const attachments = (initialOptimisticMessage?.files ?? []).map((file) => ({
      filename: file.filename ?? "file",
      mediaType: file.mediaType ?? "application/octet-stream",
    }));
    if (!text && attachments.length === 0) return null;
    return {
      id: `initial-${threadId}`,
      text,
      attachments,
      position: 0,
      createdAt: "",
      updatedAt: "",
    };
  }, [
    initialOptimisticMessage,
    initialPromptRunActive,
    meta.thread?.firstMessageContent,
    threadId,
    userMessageCount,
  ]);
  const promptQueue = usePromptQueue(
    threadId,
    run.status !== "idle",
    userMessageCount,
    meta.thread?.modelId,
  );
  const { acknowledgeClaimedPrompt, claimedPrompt, claimedPromptBaseline } =
    promptQueue;
  const optimisticPrompt =
    claimedPrompt &&
    (claimedPromptBaseline === null ||
      userMessageCount <= claimedPromptBaseline)
      ? claimedPrompt
      : null;
  const visibleOptimisticPrompt = initialOptimisticPrompt ?? optimisticPrompt;

  useEffect(() => {
    if (
      claimedPrompt == null ||
      claimedPromptBaseline === null ||
      userMessageCount <= claimedPromptBaseline
    ) {
      return;
    }
    acknowledgeClaimedPrompt(claimedPrompt.id);
  }, [
    acknowledgeClaimedPrompt,
    claimedPromptBaseline,
    claimedPrompt,
    userMessageCount,
  ]);
  const thread = meta.thread;
  const isUnread =
    readOverride !== null && readOverride.thread === thread
      ? readOverride.isUnread
      : thread?.isUnread === true;
  useEffect(() => {
    manuallyUnreadOnPage.current = false;
  }, [threadId]);
  useEffect(() => {
    const completionReady =
      successfulCompletion?.threadId === threadId &&
      successfulCompletion.sequence > readCompletionSequence.current;
    if (
      meta.status !== "ready" ||
      !transcript.hydrated ||
      run.status !== "idle" ||
      responsePendingDisplay === threadId ||
      !pageVisible ||
      readStateInFlight.current ||
      manuallyUnreadOnPage.current ||
      thread?.completedAt != null ||
      (!thread?.isUnread && !completionReady)
    ) {
      return;
    }
    readStateInFlight.current = true;
    const completionSequenceToRead = completionReady
      ? successfulCompletion.sequence
      : readCompletionSequence.current;
    const request = setThreadReadState(threadId, false)
      .then(() => {
        if (manuallyUnreadOnPage.current) return;
        readCompletionSequence.current = Math.max(
          readCompletionSequence.current,
          completionSequenceToRead,
        );
        return recheckThreadMetadata();
      })
      .catch(() => {
        // Keep the unread state. A later visibility or workspace event retries.
      })
      .finally(() => {
        if (automaticReadPromise.current === request) {
          automaticReadPromise.current = null;
        }
        readStateInFlight.current = false;
      });
    automaticReadPromise.current = request;
  }, [
    meta.status,
    pageVisible,
    recheckThreadMetadata,
    responsePendingDisplay,
    run.status,
    setThreadReadState,
    successfulCompletion,
    thread?.completedAt,
    thread?.isUnread,
    threadId,
    transcript.hydrated,
  ]);
  const completed =
    completionOverride !== null && completionOverride.thread === thread
      ? completionOverride.completed
      : thread?.completedAt != null;
  const canRetryInitial = run.canRetryInitial;
  const resourceSettings = useMemo(
    () =>
      resourceSettingsOverride?.threadId === threadId
        ? resourceSettingsOverride.settings
        : thread
          ? {
              toolMode: thread.toolMode ?? null,
              disabledMcpServerIds: thread.disabledMcpServerIds ?? [],
              disabledSkillIds: thread.disabledSkillIds ?? [],
              disabledSandboxIds: thread.disabledSandboxIds ?? [],
              disabledSubagentIds: thread.disabledSubagentIds ?? [],
            }
          : EMPTY_RESOURCE_SETTINGS,
    [resourceSettingsOverride, thread, threadId],
  );

  const updateResourceSettings = async (next: ThreadResourceSettings) => {
    if (resourceSettingsSaving) return;
    const previous = resourceSettings;
    setResourceSettingsOverride({ threadId, settings: next });
    setResourceSettingsSaving(true);
    try {
      const updated = await threadsApi.updateThreadResources(threadId, next);
      setResourceSettingsOverride({
        threadId,
        settings: {
          toolMode: updated.toolMode ?? null,
          disabledMcpServerIds: updated.disabledMcpServerIds ?? [],
          disabledSkillIds: updated.disabledSkillIds ?? [],
          disabledSandboxIds: updated.disabledSandboxIds ?? [],
          disabledSubagentIds: updated.disabledSubagentIds ?? [],
        },
      });
    } catch (error) {
      setResourceSettingsOverride({ threadId, settings: previous });
      toast.error(
        getApiErrorMessage(
          error,
          "Conversation resources could not be updated.",
        ),
      );
    } finally {
      setResourceSettingsSaving(false);
    }
  };

  const memoriesEnabled =
    memoryOverride?.threadId === threadId
      ? memoryOverride.enabled
      : thread?.memoriesEnabled !== false;

  const updateMemoriesEnabled = async (enabled: boolean) => {
    if (memorySaving || !thread) return;
    const previous = memoriesEnabled;
    setMemoryOverride({ threadId, enabled });
    setMemorySaving(true);
    try {
      const updated = await threadsApi.updateThreadMemories(threadId, enabled);
      setMemoryOverride({
        threadId,
        enabled: updated.memoriesEnabled !== false,
      });
    } catch (error) {
      setMemoryOverride({ threadId, enabled: previous });
      toast.error(
        getApiErrorMessage(
          error,
          "Conversation memories could not be updated.",
        ),
      );
    } finally {
      setMemorySaving(false);
    }
  };

  const updateCompletion = async (nextCompleted: boolean) => {
    if (completionSaving) return;
    setCompletionOverride({ thread, completed: nextCompleted });
    setCompletionSaving(true);
    try {
      await setThreadCompleted(threadId, nextCompleted);
      await Promise.allSettled([
        recheckThreadMetadata(),
        refreshThreads(),
        refreshProjectTree(),
      ]);
    } catch (error) {
      setCompletionOverride(null);
      toast.error(
        getApiErrorMessage(
          error,
          `The conversation could not be ${
            nextCompleted ? "completed" : "reopened"
          }.`,
        ),
      );
    } finally {
      setCompletionSaving(false);
    }
  };

  const updateReadState = async (nextUnread: boolean) => {
    if (readSaving) return;
    const previousManualState = manuallyUnreadOnPage.current;
    manuallyUnreadOnPage.current = nextUnread;
    setReadOverride({ thread, isUnread: nextUnread });
    setReadSaving(true);
    try {
      if (nextUnread) {
        // If the page was still finishing its automatic "read" write, let it
        // settle first so this explicit user choice is always the final write.
        await automaticReadPromise.current;
      }
      await setThreadReadState(threadId, nextUnread);
      await recheckThreadMetadata();
    } catch (error) {
      manuallyUnreadOnPage.current = previousManualState;
      setReadOverride(null);
      toast.error(
        getApiErrorMessage(error, "The read state could not be updated."),
      );
    } finally {
      setReadSaving(false);
    }
  };

  useEffect(() => {
    if (
      successfulCompletion?.threadId !== threadId ||
      successfulCompletion.sequence === playedCompletionSequence.current ||
      run.status !== "idle" ||
      promptQueue.items.length > 0 ||
      promptQueue.runStarting
    ) {
      return;
    }

    playedCompletionSequence.current = successfulCompletion.sequence;
    if (!isResponseSoundEnabled()) return;
    const audio = new Audio("/success.mp3");
    audio.play().catch(() => {});
  }, [
    promptQueue.items.length,
    promptQueue.runStarting,
    run.status,
    successfulCompletion,
    threadId,
  ]);

  const {
    acceptsFiles,
    status: agentStatus,
    detail: agentStatusDetail,
    disconnectedMcpServers,
    refetch: refetchReady,
  } = useAgentReadiness(
    meta.agentArchived ? undefined : agentId,
    resourceSettings,
  );
  // Resource failures stay visible on the plug button without replacing or
  // disabling the composer.
  const resourceWarning =
    meta.sandboxUnavailable ??
    (agentStatus === "sandbox_unavailable"
      ? (agentStatusDetail ??
        "This agent's sandbox is not available right now.")
      : agentStatus === "not_configured"
        ? "Some MCP tools are not configured."
        : agentStatus === "disconnected" &&
            disconnectedMcpServers.length === 0
          ? agentStatusDetail
      : null);

  const { setCurrentChat, clearCurrentChat, setCost } = useChatHeaderStore();
  useEffect(() => {
    if (thread) setCurrentChat(chatHeaderFromThread(thread));
  }, [thread, setCurrentChat]);
  useEffect(() => clearCurrentChat, [clearCurrentChat]);
  // The header is global: never leave the previous thread's subtotal visible
  // while the new thread is opening or running.
  useEffect(() => {
    setCost(null);
  }, [threadId, setCost]);
  // Re-read retained usage on open and whenever the durable run settles.
  useEffect(() => {
    if (run.isLoading) return;
    let stale = false;
    void getThreadCost(threadId).then(
      (cost) => {
        if (!stale) setCost(cost);
      },
      () => {
        if (!stale) setCost(null);
      },
    );
    return () => {
      stale = true;
    };
  }, [threadId, run.isLoading, setCost]);

  const completionActionDisabled =
    meta.viewerRole !== null ||
    run.status !== "idle" ||
    promptQueue.runStarting ||
    promptQueue.items.length > 0;
  const memoryActionDisabled =
    meta.viewerRole !== null ||
    completed ||
    meta.agentArchived ||
    run.status !== "idle" ||
    promptQueue.runStarting ||
    promptQueue.items.length > 0;
  const completionTooltip =
    meta.viewerRole !== null
      ? "Only the conversation owner can change completion"
      : completionActionDisabled
        ? "Wait for active and queued prompts to finish"
        : completed
          ? "Reopen conversation"
          : "Mark conversation as completed";

  return (
    <ArtifactWorkspace
      key={threadId}
      threadId={threadId}
      running={run.status !== "idle" || promptQueue.runStarting}
      editable={
        meta.status === "ready" &&
        meta.viewerRole === null &&
        !completed &&
        !meta.agentArchived
      }
      refreshKey={JSON.stringify(
        transcript.toolCalls.map((toolCall) => [toolCall.id, toolCall.status]),
      )}
      order={transcript.toolCalls.map(
        (toolCall) => toolCall.callId ?? toolCall.id,
      )}
    >
      {meta.status === "ready" && thread && (
        <ChatHeaderLeadingActions>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="inline-flex">
                <button
                  type="button"
                  aria-label={
                    completed ? "Reopen conversation" : "Complete conversation"
                  }
                  aria-pressed={completed}
                  disabled={completionActionDisabled || completionSaving}
                  onClick={() => {
                    void updateCompletion(!completed);
                  }}
                  className={`flex h-[30px] cursor-pointer items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
                    completed
                      ? "border-petrol/25 bg-petrol/8 text-petrol hover:bg-petrol/12 dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal"
                      : "border-border bg-card text-meta hover:bg-hover hover:text-foreground dark:bg-white/5"
                  }`}
                >
                  {completionSaving ? (
                    <LoaderCircle className="size-3.5 animate-spin" />
                  ) : completed ? (
                    <Undo2 className="size-3.5" />
                  ) : (
                    <CircleCheck className="size-3.5" />
                  )}
                  <span className="hidden xl:inline">
                    {completed ? "Reopen" : "Complete"}
                  </span>
                </button>
              </span>
            </TooltipTrigger>
            <TooltipContent side="bottom" sideOffset={7}>
              {completionTooltip}
            </TooltipContent>
          </Tooltip>
          {!completed && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  aria-label={isUnread ? "Mark as read" : "Mark as unread"}
                  aria-pressed={isUnread}
                  disabled={readSaving}
                  onClick={() => {
                    void updateReadState(!isUnread);
                  }}
                  className={`flex h-[30px] cursor-pointer items-center gap-1.5 rounded-full border px-2.5 text-[11.5px] font-semibold transition-colors disabled:cursor-wait disabled:opacity-50 ${
                    isUnread
                      ? "border-petrol/25 bg-petrol/8 text-petrol hover:bg-petrol/12 dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal"
                      : "border-border bg-card text-meta hover:bg-hover hover:text-foreground dark:bg-white/5"
                  }`}
                >
                  {readSaving ? (
                    <LoaderCircle className="size-3.5 animate-spin" />
                  ) : isUnread ? (
                    <MailOpen className="size-3.5" />
                  ) : (
                    <Mail className="size-3.5" />
                  )}
                  <span className="hidden xl:inline">
                    {isUnread ? "Mark read" : "Mark unread"}
                  </span>
                </button>
              </TooltipTrigger>
              <TooltipContent side="bottom" sideOffset={7}>
                {isUnread
                  ? "Mark conversation as read"
                  : "Mark conversation as unread"}
              </TooltipContent>
            </Tooltip>
          )}
          <ChatNotificationsToggle />
        </ChatHeaderLeadingActions>
      )}
      {meta.status === "ready" && (
        <ChatHeaderActions>
          <ChatMemoryToggle
            enabled={memoriesEnabled}
            saving={memorySaving}
            disabled={memoryActionDisabled}
            onChange={(enabled) => {
              void updateMemoriesEnabled(enabled);
            }}
          />
        </ChatHeaderActions>
      )}
      {meta.status === "ready" && meta.viewerRole === null && (
        <ShareConversation
          threadId={threadId}
          disabled={
            run.status !== "idle" ||
            promptQueue.runStarting ||
            transcript.messages.length === 0
          }
        />
      )}
      {meta.status === "ready" && thread && (
        <ChatMobileActionsSheet>
          <section>
            <div className="mb-2 px-1">
              <h2 className="font-display text-[15px] font-semibold text-sidebar-foreground">
                Conversation state
              </h2>
            </div>
            <div className="overflow-hidden rounded-[12px] border border-sidebar-border bg-card">
              <div className="flex min-h-14 w-full items-center justify-between gap-4 px-4 py-2.5">
                <span className="flex min-w-0 items-center gap-2.5 text-[15px] font-semibold text-sidebar-foreground">
                  {completed ? (
                    <CircleCheck className="size-[18px] shrink-0 text-emerald-600" />
                  ) : (
                    <CircleCheck className="size-[18px] shrink-0 text-sidebar-muted" />
                  )}
                  {completed ? "Complete" : "In progress"}
                </span>
                <button
                  type="button"
                  aria-pressed={completed}
                  aria-label={completed ? "Reopen conversation" : "Complete conversation"}
                  title={completed ? "Reopen conversation" : "Complete conversation"}
                  disabled={completionActionDisabled || completionSaving}
                  onClick={() => {
                    void updateCompletion(!completed);
                  }}
                  className="flex size-10 shrink-0 touch-manipulation cursor-pointer items-center justify-center rounded-[8px] bg-petrol text-white shadow-raised transition-[background-color,transform] hover:bg-petrol/90 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 dark:bg-white dark:text-ink dark:hover:bg-white/90"
                >
                  {completionSaving ? (
                    <LoaderCircle className="size-4 animate-spin" />
                  ) : completed ? (
                    <Undo2 className="size-4" />
                  ) : (
                    <CircleCheck className="size-4" />
                  )}
                </button>
              </div>

              {!completed && (
                <div className="border-t border-sidebar-border p-2">
                  <div className="grid grid-cols-2 gap-1 rounded-[9px] bg-sidebar-accent/55 p-1">
                    <button
                      type="button"
                      aria-pressed={!isUnread}
                      disabled={readSaving}
                      onClick={() => {
                        if (isUnread) void updateReadState(false);
                      }}
                      className={`flex h-11 touch-manipulation cursor-pointer items-center justify-center gap-2 rounded-[7px] text-[14px] font-semibold transition-[background-color,color,box-shadow,transform] active:scale-[0.98] disabled:cursor-wait disabled:opacity-45 ${
                        !isUnread
                          ? "bg-petrol text-white shadow-raised dark:bg-white dark:text-ink"
                          : "text-sidebar-muted hover:bg-card/70 hover:text-sidebar-foreground"
                      }`}
                    >
                      {readSaving && isUnread ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <MailOpen className="size-4" />
                      )}
                      Read
                    </button>
                    <button
                      type="button"
                      aria-pressed={isUnread}
                      disabled={readSaving}
                      onClick={() => {
                        if (!isUnread) void updateReadState(true);
                      }}
                      className={`flex h-11 touch-manipulation cursor-pointer items-center justify-center gap-2 rounded-[7px] text-[14px] font-semibold transition-[background-color,color,box-shadow,transform] active:scale-[0.98] disabled:cursor-wait disabled:opacity-45 ${
                        isUnread
                          ? "bg-petrol text-white shadow-raised dark:bg-white dark:text-ink"
                          : "text-sidebar-muted hover:bg-card/70 hover:text-sidebar-foreground"
                      }`}
                    >
                      {readSaving && !isUnread ? (
                        <LoaderCircle className="size-4 animate-spin" />
                      ) : (
                        <Mail className="size-4" />
                      )}
                      Unread
                    </button>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="mt-6">
            <div className="mb-2 px-1">
              <h2 className="font-display text-[15px] font-semibold text-sidebar-foreground">
                Context
              </h2>
            </div>
            <div className="rounded-[12px] border border-sidebar-border bg-card px-4 py-4">
              <div className="flex min-h-7 items-center gap-2.5">
                {memorySaving ? (
                  <LoaderCircle className="size-[18px] shrink-0 animate-spin text-sidebar-active-icon" />
                ) : (
                  <Brain className="size-[18px] shrink-0 text-sidebar-active-icon" />
                )}
                <span className="min-w-0 flex-1 text-[15px] font-semibold text-sidebar-foreground">
                  Memories
                </span>
                <Switch
                  className="h-6 w-11 [&_[data-slot=switch-thumb]]:size-5 [&[data-state=checked]_[data-slot=switch-thumb]]:translate-x-5"
                  checked={memoriesEnabled}
                  disabled={memoryActionDisabled || memorySaving}
                  aria-label={
                    memoriesEnabled
                      ? "Disable memories for this conversation"
                      : "Enable memories for this conversation"
                  }
                  onCheckedChange={(enabled) => {
                    void updateMemoriesEnabled(enabled);
                  }}
                />
              </div>
              <p className="mt-3 text-[13.5px] leading-5 text-sidebar-muted">
                {memoriesEnabled
                  ? "This agent can use your saved context in this conversation."
                  : "Saved context is not used in this conversation."}
              </p>
              <Link
                href="/settings?tab=profile&section=memories"
                className="mt-4 flex min-h-11 touch-manipulation items-center justify-between border-t border-sidebar-border pt-3 text-[14px] font-semibold text-sidebar-foreground transition-colors hover:text-sidebar-active-icon"
              >
                Manage saved memories
                <ChevronRight className="size-4" />
              </Link>
            </div>
          </section>

          <ChatMobileNotificationsSection />

          {meta.viewerRole === null && (
            <section className="mt-6">
              <ShareConversation
                threadId={threadId}
                variant="menu"
                disabled={
                  run.status !== "idle" ||
                  promptQueue.runStarting ||
                  transcript.messages.length === 0
                }
              />
            </section>
          )}
        </ChatMobileActionsSheet>
      )}
      <div className="h-full flex flex-col w-full overflow-hidden">
        <div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
          <Conversation
            initial={scrolledThreadId === threadId ? "instant" : "smooth"}
          >
            <ConversationContent className="max-w-4xl mx-auto w-full pb-16 lg:px-10 sm:px-6 px-2">
              <ConversationBody
                key={threadId}
                agentId={agentId}
                messages={transcript.messages}
                runs={transcript.runs}
                toolCalls={transcript.toolCalls}
                subagents={transcript.subagents}
                stream={transcript.stream}
                supervisorTodos={transcript.todos}
                isLoading={run.isLoading}
                isStarting={run.isStarting}
                isInterrupted={run.status === "interrupted"}
                hitlToolNames={hitl.hitlToolNames}
                decisions={hitl.decisions}
                recordDecision={hitl.recordDecision}
                nestedInterrupts={hitl.nestedInterrupts}
                elicitation={
                  isElicitation(hitl.interrupt?.value)
                    ? hitl.interrupt
                    : null
                }
                respond={actions.respond}
                modelUnavailable={!meta.modelAvailable}
                readOnly={
                  completed ||
                  meta.viewerRole !== null ||
                  meta.agentArchived
                }
                onRegenerate={() => {
                  acknowledgeCurrentResponse();
                  actions.regenerate();
                }}
                optimisticPrompt={visibleOptimisticPrompt}
                emptyPrompt={thread?.firstMessageContent?.trim() || null}
                canRetryInitial={canRetryInitial}
                showEmptyState={meta.status === "ready" && transcript.hydrated}
                onRetryInitialPrompt={() => {
                  if (canRetryInitial) {
                    void actions.retryInitial().catch((error: unknown) => {
                      toast.error(
                        getApiErrorMessage(
                          error,
                          "The original message could not be retried.",
                        ),
                      );
                    });
                    return;
                  }
                  const prompt = thread?.firstMessageContent?.trim();
                  if (!prompt) return;
                  acknowledgeCurrentResponse();
                  void actions
                    .send({ text: prompt, files: [] })
                    .catch((error: unknown) => {
                      toast.error(
                        getApiErrorMessage(
                          error,
                          "The message could not be sent.",
                        ),
                      );
                    });
                }}
                hydrationError={transcript.hydrationError}
                onRetryHydration={() => {
                  void actions.rehydrate().catch(() => {});
                }}
                error={run.error}
                rehydratedError={run.rehydratedError}
              />
            </ConversationContent>
            <ConversationScrollButton />
          </Conversation>
          <ThreadMap messages={transcript.messages} />
          <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-background to-transparent z-10" />
        </div>
        <div className="w-full shrink-0 bg-background">
          {meta.status === "ready" &&
            meta.viewerRole === null &&
            !meta.agentArchived &&
            !meta.modelAvailable && (
              <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 pt-6">
                <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
                  <CircleSlash className="size-5 shrink-0 text-muted-foreground" />
                  <p className="flex-1 text-sm text-muted-foreground">
                    The model used by this conversation
                    {thread?.modelId ? ` (${thread.modelId})` : ""} is no longer
                    available in this workspace. Choose another model below, or
                    ask a workspace admin to restore it.
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="shrink-0 cursor-pointer"
                    onClick={() => {
                      void actions.recheckModel();
                    }}
                  >
                    Check again
                  </Button>
                </div>
              </div>
            )}
          {meta.status === "error" ? (
            <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
              <div className="flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3">
                <AlertTriangle className="size-5 shrink-0 text-destructive" />
                <p className="flex-1 text-sm text-destructive">
                  {getApiErrorMessage(
                    openError,
                    "This conversation could not be loaded.",
                  )}
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="shrink-0 cursor-pointer"
                  onClick={actions.reopen}
                >
                  Retry
                </Button>
              </div>
            </div>
          ) : meta.viewerRole !== null ? (
            <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
              <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
                <ShieldCheck className="size-5 shrink-0 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  {meta.viewerRole === "admin"
                    ? "Viewing as admin, this conversation belongs to another user and is read-only."
                    : "This conversation is shared through its project and is read-only."}
                </p>
              </div>
            </div>
          ) : meta.agentArchived ? (
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
          ) : meta.status !== "ready" ? (
            // Metadata still loading (first open, or a Retry in flight): no
            // composer yet, so nothing can be sent alongside a parked message.
            <div
              className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-4"
              aria-busy="true"
            />
          ) : transcript.hydrationError != null ? (
            <div
              className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-4"
              aria-busy="false"
            />
          ) : (
            <ChatPromptInput
              key={threadId}
              agentId={agentId}
              draftKey={threadId}
              onSubmit={(message) => {
                acknowledgeCurrentResponse();
                return actions.send(message, {
                  fileStorage: acceptsFiles === true,
                });
              }}
              status={run.isLoading ? "streaming" : "ready"}
              queueMode={run.status === "streaming" && !run.isStopping}
              submissionDisabled={
                !meta.modelAvailable ||
                run.isStopping ||
                memorySaving ||
                completed
              }
              completed={completed}
              reopening={completionSaving}
              onReopen={() => {
                void updateCompletion(false);
              }}
              className="w-full max-w-4xl mx-auto px-3 py-2 sm:px-6 sm:py-4 lg:px-10"
              stop={actions.stop}
              stopping={run.isStopping}
              selectedModel={thread?.modelId ?? undefined}
              onModelChange={actions.changeModel}
              modelChangeDisabled={
                run.status !== "idle" || promptQueue.runStarting
              }
              selectedEffort={thread?.reasoningEffort ?? null}
              onEffortChange={actions.changeReasoningEffort}
              acceptsFiles={acceptsFiles}
              disconnectedServers={disconnectedMcpServers}
              resourceWarning={resourceWarning}
              onAllConnected={() => {
                actions.recheckSandbox();
                refetchReady();
              }}
              resourceSettings={resourceSettings}
              onResourceSettingsChange={(settings) => {
                void updateResourceSettings(settings);
              }}
              resourceSettingsSaving={resourceSettingsSaving}
              conversationMessages={transcript.messages}
              loadLatestConversationMessages={actions.loadLatestMessages}
              queuedPrompts={promptQueue.items}
              queueLoading={promptQueue.isLoading}
              onQueueAuthorizationRequired={refetchReady}
              onEnqueue={async (message) => {
                await promptQueue.enqueue(message, {
                  fileStorage: acceptsFiles === true,
                });
              }}
              onUpdateQueued={async (id, text) => {
                await promptQueue.update(id, text);
              }}
              onBeginQueuedEdit={promptQueue.beginEdit}
              onEndQueuedEdit={promptQueue.endEdit}
              onSendQueuedNow={promptQueue.sendNow}
              sendQueuedNowDisabled={
                run.status === "interrupted" || run.isStopping
              }
              onRemoveQueued={promptQueue.remove}
              onReorderQueued={promptQueue.reorder}
            />
          )}
        </div>
      </div>
    </ArtifactWorkspace>
  );
};

export default ChatPage;

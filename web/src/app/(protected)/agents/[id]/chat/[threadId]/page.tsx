"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { BaseMessage } from "@langchain/core/messages";
import {
  isAIMessage,
  isHumanMessage,
} from "@langchain/core/messages";
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
  CircleSlash,
  ServerCrash,
  ShieldCheck,
} from "lucide-react";
import { useParams } from "next/navigation";
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
import type { ThreadResourceSettings } from "@/types/threads";
import type { QueuedPrompt } from "@/types/runs";
import { ArtifactWorkspace } from "@/components/artifacts/workspace";
import { useThreadsStore } from "@/stores/threads-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useWorkspaceEventsStore } from "@/stores/workspace-events-store";
import {
  ChatHeaderActions,
  ChatMemoryToggle,
} from "@/components/layout/chat-header";

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
  const [completionOverride, setCompletionOverride] = useState<{
    threadId: string;
    completed: boolean;
  } | null>(null);
  const [reopening, setReopening] = useState(false);
  const threadsVersion = useWorkspaceEventsStore(
    (state) => state.threadsVersion,
  );
  const setThreadCompleted = useThreadsStore(
    (state) => state.setThreadCompleted,
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
      if (assistantId !== null && assistantId === acknowledgedAssistantId.current) {
        return;
      }
      acknowledgedAssistantId.current = assistantId;
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
        if (completionTimer.current !== null) clearTimeout(completionTimer.current);
        return;
      }
      settleSuccessfulCompletion(candidate);
    },
  });
  const recheckThreadMetadata = actions.recheckModel;
  useEffect(() => {
    if (threadsVersion === 0 || meta.status !== "ready") return;
    void recheckThreadMetadata();
  }, [meta.status, recheckThreadMetadata, threadsVersion]);
  useEffect(() => {
    transcriptMessages.current = transcript.messages;
  }, [transcript.messages]);
  useEffect(() => {
    runStatusRef.current = run.status;
  }, [run.status]);
  useEffect(
    () => () => {
      completionCandidate.current += 1;
      if (completionTimer.current !== null) clearTimeout(completionTimer.current);
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
  const {
    acknowledgeClaimedPrompt,
    claimedPrompt,
    claimedPromptBaseline,
  } = promptQueue;
  const optimisticPrompt =
    claimedPrompt &&
    (claimedPromptBaseline === null ||
      userMessageCount <= claimedPromptBaseline)
      ? claimedPrompt
      : null;
  const visibleOptimisticPrompt =
    initialOptimisticPrompt ?? optimisticPrompt;

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
  const completed =
    completionOverride?.threadId === threadId
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
        getApiErrorMessage(error, "Conversation resources could not be updated."),
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

  const reopenConversation = async () => {
    if (reopening) return;
    setReopening(true);
    try {
      await setThreadCompleted(threadId, false);
      setCompletionOverride({ threadId, completed: false });
      await Promise.allSettled([refreshThreads(), refreshProjectTree()]);
    } catch (error) {
      toast.error(
        getApiErrorMessage(error, "The conversation could not be reopened."),
      );
    } finally {
      setReopening(false);
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
    ready: agentReady,
    acceptsFiles,
    status: agentStatus,
    detail: agentStatusDetail,
    disconnectedMcpServers,
    refetch: refetchReady,
  } = useAgentReadiness(
    meta.agentArchived ? undefined : agentId,
    resourceSettings,
  );
  // Two ways the sandbox can be down: readiness said so when the page opened,
  // or a command 409'd mid-session after the provider fell over. One notice
  // either way, cleared by "Check again".
  const sandboxDown =
    meta.sandboxUnavailable ??
    (agentStatus === "sandbox_unavailable"
      ? (agentStatusDetail ??
        "This agent's sandbox is not available right now.")
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
        transcript.toolCalls.map((toolCall) => [
          toolCall.id,
          toolCall.status,
        ]),
      )}
      order={transcript.toolCalls.map(
        (toolCall) => toolCall.callId ?? toolCall.id,
      )}
    >
      {meta.status === "ready" && (
        <ChatHeaderActions>
          <ChatMemoryToggle
            enabled={memoriesEnabled}
            saving={memorySaving}
            disabled={
              meta.viewerRole !== null ||
              completed ||
              meta.agentArchived ||
              run.status !== "idle" ||
              promptQueue.runStarting ||
              promptQueue.items.length > 0
            }
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
      <div className="h-full flex flex-col w-full overflow-hidden">
      <div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
        <Conversation>
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
              respond={actions.respond}
              modelUnavailable={!meta.modelAvailable}
              readOnly={completed}
              onRegenerate={() => {
                acknowledgeCurrentResponse();
                actions.regenerate();
              }}
              optimisticPrompt={visibleOptimisticPrompt}
              emptyPrompt={thread?.firstMessageContent?.trim() || null}
              canRetryInitial={canRetryInitial}
              showEmptyState={
                meta.status === "ready" && transcript.hydrated
              }
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
                      getApiErrorMessage(error, "The message could not be sent."),
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
        ) : sandboxDown ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
              <ServerCrash className="size-5 shrink-0 text-muted-foreground" />
              <p className="flex-1 text-sm text-muted-foreground">
                {sandboxDown} Try again in a moment, or ask a workspace admin.
              </p>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0 cursor-pointer"
                onClick={() => {
                  actions.recheckSandbox();
                  refetchReady();
                }}
              >
                Check again
              </Button>
            </div>
          </div>
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
              !meta.modelAvailable || run.isStopping || memorySaving || completed
            }
            completed={completed}
            reopening={reopening}
            onReopen={() => {
              void reopenConversation();
            }}
            className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-4"
            stop={actions.stop}
            stopping={run.isStopping}
            selectedModel={thread?.modelId ?? undefined}
            onModelChange={actions.changeModel}
            modelChangeDisabled={
              run.status !== "idle" || promptQueue.runStarting
            }
            selectedEffort={thread?.reasoningEffort ?? null}
            onEffortChange={actions.changeReasoningEffort}
            agentReady={agentReady}
            acceptsFiles={acceptsFiles}
            disconnectedServers={disconnectedMcpServers}
            onAllConnected={refetchReady}
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

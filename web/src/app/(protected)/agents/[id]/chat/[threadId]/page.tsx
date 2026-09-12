"use client";

import { useEffect } from "react";
import {
  Conversation,
  ConversationContent,
  ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import ChatPromptInput from "../components/prompt-input";
import { AlertTriangle, ArchiveIcon, CircleSlash, ShieldCheck } from "lucide-react";
import { useParams } from "next/navigation";
import { useAgentsStore } from "@/stores/agents-store";
import { canConfigureAgent } from "@/types/agents";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { chatHeaderFromThread, useThreadSession } from "@/lib/thread-session";
import { getApiErrorMessage } from "@/lib/api/errors";
import { ConversationBody } from "./conversation-body";

/**
 * The chat page renders one thread session. Run state, HITL, hydration and
 * the failed-run error all come from `useThreadSession`; this file owns only
 * what is visual — the banners, the composer and the header sync.
 */
const ChatPage = () => {
  const params = useParams();
  const agentId = params.id as string;
  const threadId = params.threadId as string;

  const { meta, openError, run, transcript, hitl, actions } = useThreadSession({
    threadId,
    agentId,
    onStaleInterrupt: () => {
      window.location.reload();
    },
    onCompleted: () => {
      const audio = new Audio("/success.mp3");
      audio.play().catch(() => {});
    },
  });
  const thread = meta.thread;

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
  } = useAgentReadiness(meta.agentArchived ? undefined : agentId);

  const { setCurrentChat, clearCurrentChat } = useChatHeaderStore();
  useEffect(() => {
    if (thread) setCurrentChat(chatHeaderFromThread(thread));
  }, [thread, setCurrentChat]);
  useEffect(() => clearCurrentChat, [clearCurrentChat]);

  return (
    <div className="h-full flex flex-col w-full overflow-hidden">
      <div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
        <Conversation>
          <ConversationContent className="max-w-4xl mx-auto w-full lg:px-10 sm:px-6 px-2">
            <ConversationBody
              messages={transcript.messages}
              toolCalls={transcript.toolCalls}
              subagents={transcript.subagents}
              stream={transcript.stream}
              supervisorTodos={transcript.todos}
              isLoading={run.isLoading}
              isInterrupted={run.status === "interrupted"}
              hitlToolNames={hitl.hitlToolNames}
              decisions={hitl.decisions}
              recordDecision={hitl.recordDecision}
              nestedInterrupts={hitl.nestedInterrupts}
              respond={actions.respond}
              modelUnavailable={!meta.modelAvailable}
              onRegenerate={actions.regenerate}
              error={run.error}
              rehydratedError={run.rehydratedError}
            />
          </ConversationContent>
          <ConversationScrollButton />
        </Conversation>
        <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-background to-transparent z-10" />
      </div>
      <div className="w-full shrink-0 bg-background">
        {meta.status === "error" ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
            <div className="flex items-center gap-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3">
              <AlertTriangle className="size-5 shrink-0 text-destructive" />
              <p className="flex-1 text-sm text-destructive">
                {getApiErrorMessage(openError, "This conversation could not be loaded.")}
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
        ) : meta.viewerRole === "admin" ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
              <ShieldCheck className="size-5 shrink-0 text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                Viewing as admin — this thread belongs to another user and is
                read-only.
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
        ) : !meta.modelAvailable ? (
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-6">
            <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
              <CircleSlash className="size-5 shrink-0 text-muted-foreground" />
              <p className="flex-1 text-sm text-muted-foreground">
                The model used by this conversation
                {thread?.modelId ? ` (${thread.modelId})` : ""} is no longer
                available in this workspace. Ask a workspace admin to restore
                it, or start a new conversation.
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
        ) : meta.status !== "ready" ? (
          // Metadata still loading (first open, or a Retry in flight): no
          // composer yet, so nothing can be sent alongside a parked message.
          <div className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-4" aria-busy="true" />
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
            onSubmit={actions.send}
            status={run.isLoading ? "streaming" : "ready"}
            className="w-full max-w-4xl mx-auto lg:px-10 sm:px-6 px-3 py-4"
            stop={actions.stop}
            selectedModel={thread?.modelId ?? undefined}
            readOnlyModel={true}
            selectedEffort={thread?.reasoningEffort ?? null}
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

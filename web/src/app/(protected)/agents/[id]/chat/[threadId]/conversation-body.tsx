"use client";

import { Fragment, memo, useCallback, useMemo } from "react";
import Image from "next/image";
import type { BaseMessage } from "@langchain/core/messages";
import {
  isAIMessage,
  isHumanMessage,
  isToolMessage,
} from "@langchain/core/messages";
import type { AnyStream, SubagentDiscoverySnapshot } from "@langchain/react";
import { CopyIcon, RefreshCcwIcon } from "lucide-react";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  ChainOfThought,
  ChainReasoningStep,
  ChainThinking,
} from "@/components/ai-elements/chain-of-thought";
import {
  Error,
  ErrorContent,
  ErrorDetails,
} from "@/components/ai-elements/error";
import {
  Attachment,
  AttachmentHoverCard,
  AttachmentHoverCardContent,
  AttachmentHoverCardTrigger,
  AttachmentInfo,
  AttachmentPreview,
  Attachments,
  getAttachmentLabel,
  getMediaCategory,
} from "@/components/ai-elements/attachments";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useAgentsStore } from "@/stores/agents-store";
import type { HitlDecision } from "@/hooks/use-hitl-approvals";
import { McpAppWidget } from "../components/mcp-app-widget";
import {
  type ChainStepData,
  type ToolCallView,
  getFileAttachments,
  getMcpAppInfo,
  getReasoning,
  getStructuredContent,
  getToolStepState,
  groupChains,
  sanitizeToolIdentifier,
} from "./message-helpers";
import {
  SubAgentCard,
  SubAgentProgress,
  SynthesisIndicator,
} from "./subagent-card";
import { type DescribeTool, ToolStep, useDescribeTool } from "./tool-step";

export type ConversationBodyProps = {
  /** Throttled `stream.messages` (or the hydrated history when idle). */
  messages: BaseMessage[];
  /** `pairToolCalls(messages, stream.toolCalls)`, memoized by the page. */
  toolCalls: ToolCallView[];
  /** `stream.subagents` — discovery snapshots keyed by `task` tool-call id. */
  subagents: ReadonlyMap<string, SubagentDiscoverySnapshot>;
  /** Identity-stable stream handle for the cards' scoped subscriptions. */
  stream: AnyStream;
  supervisorTodos: Todo[];
  isLoading: boolean;
  isInterrupted: boolean;
  hitlToolNames: Set<string> | null;
  decisions: Partial<Record<string, HitlDecision>>;
  recordDecision: (toolCallId: string, decision: HitlDecision) => void;
  modelUnavailable: boolean;
  onRegenerate: () => void;
  error: unknown;
  rehydratedError: string | null;
};

/**
 * The conversation render tree, memoized so the page that owns `useStream`
 * (notified on every store tick) renders almost nothing itself. Every prop is
 * either throttled or identity-stable between ticks.
 */
export const ConversationBody = memo(function ConversationBody({
  messages,
  toolCalls,
  subagents,
  stream,
  supervisorTodos,
  isLoading,
  isInterrupted,
  hitlToolNames,
  decisions,
  recordDecision,
  modelUnavailable,
  onRegenerate,
  error,
  rehydratedError,
}: ConversationBodyProps) {
  const { mcpServers } = useMcpServersStore();
  const workspaceAgents = useAgentsStore((s) => s.agents);
  const describe = useDescribeTool(mcpServers);

  const findAgent = useCallback(
    (subagentType: string) =>
      workspaceAgents.find(
        (a) => sanitizeToolIdentifier(a.name) === subagentType,
      ) ??
      workspaceAgents.find(
        (a) =>
          a.name.toLowerCase() ===
          subagentType.replaceAll("_", " ").toLowerCase(),
      ),
    [workspaceAgents],
  );

  const chains = useMemo(
    () => groupChains(messages, toolCalls),
    [messages, toolCalls],
  );

  const last = messages.at(-1);
  const assistantStreaming = isLoading && last != null && isAIMessage(last);
  // The assistant has started a message but produced no text or tool call
  // yet: its reasoning is what's streaming.
  const preamble =
    assistantStreaming &&
    last.text.length === 0 &&
    !toolCalls.some((tc) => tc.messageId === last.id);
  const reasoningStreamingId =
    preamble && getReasoning(last) ? (last.id ?? null) : null;
  // "Thinking…" until anything at all arrives.
  const showThinking =
    isLoading &&
    last != null &&
    (isHumanMessage(last) || (preamble && reasoningStreamingId == null));
  let lastVisibleIndex = messages.length - 1;
  while (lastVisibleIndex >= 0 && isToolMessage(messages[lastVisibleIndex])) {
    lastVisibleIndex -= 1;
  }

  return (
    <>
      {supervisorTodos.length > 0 && (
        <TodoList
          todos={supervisorTodos}
          className="mb-4 rounded-lg border border-border/50 bg-muted/30 p-4"
        />
      )}
      {messages.map((message, index) => {
        const key = message.id ?? index;
        if (isHumanMessage(message)) {
          return <UserTurn key={key} message={message} />;
        }
        if (!isAIMessage(message)) return null;

        const text = message.text;
        const chain = message.id ? chains.get(message.id) : undefined;
        const isLast = index === lastVisibleIndex;

        return (
          <Fragment key={key}>
            {chain && (
              <Chain
                steps={chain}
                reasoningStreamingId={reasoningStreamingId}
                subagents={subagents}
                stream={stream}
                describe={describe}
                findAgent={findAgent}
                isInterrupted={isInterrupted}
                hitlToolNames={hitlToolNames}
                decisions={decisions}
                recordDecision={recordDecision}
                modelUnavailable={modelUnavailable}
                coordinatorStreaming={assistantStreaming && isLast}
              />
            )}
            {text && (
              <>
                <Message from="assistant">
                  <MessageContent>
                    <MessageResponse>{text}</MessageResponse>
                  </MessageContent>
                </Message>
                {!isLoading && isLast && (
                  <MessageActions>
                    {!modelUnavailable && (
                      <MessageAction onClick={onRegenerate} label="Retry">
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
      })}

      {showThinking && <ChainThinking />}

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
    </>
  );
});

const UserTurn = ({ message }: { message: BaseMessage }) => {
  const text = message.text;
  const attachments = getFileAttachments(message);
  return (
    <>
      {attachments.length > 0 && (
        <div className="flex justify-end">
          <Attachments variant="inline">
            {attachments.map((attachment) => {
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
                      {getMediaCategory(attachment) === "image" &&
                        "url" in attachment &&
                        attachment.url && (
                          <div className="flex items-center justify-center overflow-hidden rounded-md border">
                            <Image
                              alt={label}
                              className="object-contain"
                              height={200}
                              src={attachment.url}
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
    </>
  );
};

type ChainProps = {
  steps: ChainStepData[];
  /** The AI message whose reasoning is still streaming, if any. */
  reasoningStreamingId: string | null;
  subagents: ReadonlyMap<string, SubagentDiscoverySnapshot>;
  stream: AnyStream;
  describe: DescribeTool;
  findAgent: (subagentType: string) => SubAgentCardAgent | undefined;
  isInterrupted: boolean;
  hitlToolNames: Set<string> | null;
  decisions: Partial<Record<string, HitlDecision>>;
  recordDecision: (toolCallId: string, decision: HitlDecision) => void;
  modelUnavailable: boolean;
  coordinatorStreaming: boolean;
};

type SubAgentCardAgent = NonNullable<
  React.ComponentProps<typeof SubAgentCard>["agent"]
>;

/** One turn's chain of thought: reasoning, tool steps and subagent cards on
 *  the rail, then the MCP app widgets of any tool that returned one. */
const Chain = ({
  steps: chainSteps,
  reasoningStreamingId,
  subagents,
  stream,
  describe,
  findAgent,
  isInterrupted,
  hitlToolNames,
  decisions,
  recordDecision,
  modelUnavailable,
  coordinatorStreaming,
}: ChainProps) => {
  const steps = chainSteps
    .filter((s): s is Extract<ChainStepData, { kind: "tool" }> => s.kind === "tool")
    .map(({ tc }) => ({
      tc,
      sub: tc.name === "task" ? subagents.get(tc.id) : undefined,
      state: getToolStepState(tc, isInterrupted, hitlToolNames),
    }));
  const byCall = new Map(steps.map((s) => [s.tc.id, s]));
  const chainSubagents = steps
    .map((s) => s.sub)
    .filter((s): s is SubagentDiscoverySnapshot => s != null);
  const subagentCount = steps.filter((s) => s.tc.name === "task").length;
  const reasoningStreaming = chainSteps.some(
    (s) => s.kind === "reasoning" && s.messageId === reasoningStreamingId,
  );

  return (
    <div className="w-full space-y-2">
      <ChainOfThought
        active={
          reasoningStreaming ||
          steps.some((s) =>
            s.sub ? s.sub.status === "running" : s.state === "running",
          )
        }
        lockOpen={steps.some(
          (s) => !s.sub && s.state === "awaiting-approval" && !decisions[s.tc.id],
        )}
        toolCount={steps.length - subagentCount}
        subagentCount={subagentCount}
      >
        {chainSteps.map((step) => {
          if (step.kind === "reasoning") {
            return (
              <ChainReasoningStep
                key={step.id}
                text={step.text}
                streaming={step.messageId === reasoningStreamingId}
              />
            );
          }
          const { tc, sub, state } = byCall.get(step.id)!;
          return sub ? (
            <SubAgentCard
              key={sub.id}
              subagent={sub}
              stream={stream}
              describe={describe}
              agent={findAgent(sub.name)}
            />
          ) : (
            <ToolStep
              key={tc.id}
              tc={tc}
              state={state}
              describe={describe}
              approval={
                state === "awaiting-approval"
                  ? {
                      decided: decisions[tc.id],
                      disabled: modelUnavailable,
                      onDecide: (decision) => {
                        recordDecision(tc.id, decision);
                      },
                    }
                  : undefined
              }
            />
          );
        })}
      </ChainOfThought>
      {chainSubagents.length > 0 && (
        <>
          <SubAgentProgress subagents={chainSubagents} />
          <SynthesisIndicator
            subagents={chainSubagents}
            isCoordinatorStreaming={coordinatorStreaming}
          />
        </>
      )}
      {steps.map(({ tc, sub }) => {
        const app = sub ? null : getMcpAppInfo(tc);
        if (!app) return null;
        return (
          <McpAppWidget
            key={`app-${tc.id}`}
            input={tc.args}
            output={tc.output}
            structuredContent={getStructuredContent(tc)}
            errorText={tc.error}
            toolName={describe(tc.name).toolName}
            appToolInfo={app}
          />
        );
      })}
    </div>
  );
};

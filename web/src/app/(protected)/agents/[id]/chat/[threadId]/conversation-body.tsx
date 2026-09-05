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
import type { Interrupt } from "@langchain/langgraph-sdk";
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
import type { HitlDecision, HitlResponse } from "@/hooks/use-hitl-approvals";
import { McpAppWidget } from "../components/mcp-app-widget";
import {
  type ChainStepData,
  type ToolCallView,
  type ToolStepState,
  getFileAttachments,
  getMcpAppInfo,
  getReasoning,
  getStructuredContent,
  getToolStepState,
  groupChains,
  sanitizeToolIdentifier,
  sameNamespace,
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
  /** Interrupts raised inside subagents (`stream.interrupts` minus the root
   *  one); each card claims its own and approves it itself. */
  nestedInterrupts: Interrupt[];
  /** Resume an interrupt — `stream.respond(response, { interruptId })`. */
  respond: (response: HitlResponse, interruptId: string | null) => void;
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
  nestedInterrupts,
  respond,
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
  const lastVisibleIndex = messages.findLastIndex((m) => !isToolMessage(m));

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
                nestedInterrupts={nestedInterrupts}
                respond={respond}
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
  nestedInterrupts: Interrupt[];
  respond: (response: HitlResponse, interruptId: string | null) => void;
  modelUnavailable: boolean;
  coordinatorStreaming: boolean;
};

type SubAgentCardAgent = NonNullable<
  React.ComponentProps<typeof SubAgentCard>["agent"]
>;

type ToolRow = {
  kind: "tool";
  tc: ToolCallView;
  /** The discovered subagent, for a `task` call the SDK has bound. */
  sub: SubagentDiscoverySnapshot | undefined;
  state: ToolStepState;
};
type ChainRow = Extract<ChainStepData, { kind: "reasoning" }> | ToolRow;

/** One turn's chain of thought: reasoning, tool steps and subagent cards on
 *  the rail, then the MCP app widgets of any tool that returned one. */
const Chain = ({
  steps,
  reasoningStreamingId,
  subagents,
  stream,
  describe,
  findAgent,
  isInterrupted,
  hitlToolNames,
  decisions,
  recordDecision,
  nestedInterrupts,
  respond,
  modelUnavailable,
  coordinatorStreaming,
}: ChainProps) => {
  const rows: ChainRow[] = steps.map((step) =>
    step.kind === "reasoning"
      ? step
      : {
          kind: "tool",
          tc: step.tc,
          sub: step.tc.name === "task" ? subagents.get(step.tc.id) : undefined,
          state: getToolStepState(step.tc, isInterrupted, hitlToolNames),
        },
  );
  const tools = rows.filter((r): r is ToolRow => r.kind === "tool");
  const chainSubagents = tools
    .map((r) => r.sub)
    .filter((s): s is SubagentDiscoverySnapshot => s != null);
  const reasoningStreaming = rows.some(
    (r) => r.kind === "reasoning" && r.messageId === reasoningStreamingId,
  );
  // A subagent of this chain may be paused on an approval. Exact by
  // namespace when the SDK has bound it; otherwise any running card could be
  // the one (the card itself matches by content), so keep the chain open.
  const pausedSubagents = chainSubagents.filter(
    (s) =>
      s.status === "running" &&
      (nestedInterrupts.some((i) => sameNamespace(i.namespace, s.namespace)) ||
        (nestedInterrupts.length > 0 &&
          !nestedInterrupts.some((i) =>
            chainSubagents.some((c) => sameNamespace(i.namespace, c.namespace)),
          ))),
  );

  return (
    <div className="w-full space-y-2">
      <ChainOfThought
        active={
          reasoningStreaming ||
          tools.some((r) =>
            r.sub
              ? r.sub.status === "running" && !pausedSubagents.includes(r.sub)
              : r.state === "running",
          )
        }
        lockOpen={
          pausedSubagents.length > 0 ||
          tools.some(
            (r) => !r.sub && r.state === "awaiting-approval" && !decisions[r.tc.id],
          )
        }
        toolCount={tools.length - chainSubagents.length}
        subagentCount={chainSubagents.length}
      >
        {rows.map((row) => {
          if (row.kind === "reasoning") {
            return (
              <ChainReasoningStep
                key={row.id}
                text={row.text}
                streaming={row.messageId === reasoningStreamingId}
              />
            );
          }
          const { tc, sub, state } = row;
          return sub ? (
            <SubAgentCard
              key={sub.id}
              subagent={sub}
              stream={stream}
              describe={describe}
              agent={findAgent(sub.name)}
              interrupts={nestedInterrupts}
              respond={respond}
              modelUnavailable={modelUnavailable}
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
      {tools.map(({ tc, sub }) => {
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

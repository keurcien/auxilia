"use client";

import { Fragment, memo, useMemo, useState } from "react";
import { Loader2, XCircleIcon } from "lucide-react";
import { isAIMessage } from "@langchain/core/messages";
import type { BaseMessage } from "@langchain/core/messages";
import { useMessages, useToolCalls, useValues } from "@langchain/react";
import type { AnyStream, SubagentDiscoverySnapshot } from "@langchain/react";
import { Loader } from "@/components/ai-elements/loader";
import {
  ChainRail,
  ChainReasoningLine,
  ChainStep,
  StepCode,
  StepSection,
} from "@/components/ai-elements/chain-of-thought";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { MessageResponse } from "@/components/ai-elements/message";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import { cn } from "@/lib/utils";
import {
  type ToolCallView,
  getToolStepState,
  pairToolCalls,
} from "./message-helpers";
import { type DescribeTool, ToolStep } from "./tool-step";

const formatElapsed = (ms: number) => {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
};

/** The subagent's own conversation as a nested rail: ✦ italic lines for its
 *  text, nested tool steps for its calls — the same views as the root. */
const SubAgentConversation = memo(function SubAgentConversation({
  messages,
  toolCalls,
  isStreaming,
  describe,
}: {
  messages: BaseMessage[];
  toolCalls: ToolCallView[];
  isStreaming: boolean;
  describe: DescribeTool;
}) {
  const byMessage = new Map<string, ToolCallView[]>();
  for (const tc of toolCalls) {
    if (!tc.messageId) continue;
    byMessage.set(tc.messageId, [...(byMessage.get(tc.messageId) ?? []), tc]);
  }
  const last = messages.length - 1;

  return (
    <ChainRail>
      {messages.map((message, i) => {
        if (!isAIMessage(message)) return null;
        const text = message.text;
        const calls = message.id ? (byMessage.get(message.id) ?? []) : [];
        return (
          <Fragment key={message.id ?? i}>
            {text && (
              <ChainReasoningLine>
                {text}
                {isStreaming && i === last && calls.length === 0 && (
                  <span className="ml-0.5 inline-block h-3 w-1 animate-pulse rounded-sm bg-petrol align-text-bottom" />
                )}
              </ChainReasoningLine>
            )}
            {calls.map((tc) => (
              <ToolStep
                key={tc.id}
                tc={tc}
                state={getToolStepState(tc)}
                describe={describe}
                nested
              />
            ))}
          </Fragment>
        );
      })}
    </ChainRail>
  );
});

export type SubAgentCardProps = {
  /** Discovery snapshot from `stream.subagents` (keyed by task tool-call id). */
  subagent: SubagentDiscoverySnapshot;
  /** The card opens its own scoped projections on the subagent's namespace
   *  (mount = subscribe, unmount = unsubscribe); an idle thread's history is
   *  seeded by the SDK from `POST /threads/{id}/history`. */
  stream: AnyStream;
  describe: DescribeTool;
  /** The workspace agent behind this subagent, for its emoji/pastel tile. */
  agent?: { name: string; emoji?: string | null; color?: string | null };
};

export const SubAgentCard = memo(function SubAgentCard({
  subagent,
  stream,
  describe,
  agent,
}: SubAgentCardProps) {
  const { status, startedAt, completedAt } = subagent;
  const messages = useMessages(stream, subagent);
  const liveToolCalls = useToolCalls(stream, subagent);
  const values = useValues<Record<string, unknown>>(stream, subagent);
  const toolCalls = useMemo(
    () => pairToolCalls(messages, liveToolCalls),
    [messages, liveToolCalls],
  );

  const isStreaming = status === "running";
  const isError = status === "error";
  const todos = (values?.todos ?? []) as Todo[];
  const result =
    subagent.output == null
      ? undefined
      : typeof subagent.output === "string"
        ? subagent.output
        : JSON.stringify(subagent.output, null, 2);
  // Hydrated snapshots stamp both dates at load time — nothing to show then.
  const elapsed =
    completedAt != null && completedAt.getTime() > startedAt.getTime()
      ? completedAt.getTime() - startedAt.getTime()
      : undefined;

  // Streaming and errored cards start open; a card re-opens when its
  // subagent starts streaming again.
  const [autoOpen, setAutoOpen] = useState(isStreaming || isError);
  const [wasStreaming, setWasStreaming] = useState(isStreaming);
  if (isStreaming !== wasStreaming) {
    setWasStreaming(isStreaming);
    if (isStreaming) setAutoOpen(true);
  }

  return (
    <ChainStep
      node={
        <AgentAvatar
          color={agent?.color}
          emoji={agent?.emoji}
          size="2xs"
          className="relative z-[1]"
        />
      }
      title={`Ask ${agent?.name ?? subagent.name.replaceAll("_", " ")}`}
      summary={subagent.taskInput}
      lockOpen={autoOpen}
      onOpenChange={() => {
        setAutoOpen(false);
      }}
      meta={
        isStreaming ? (
          <Loader2 className="size-3 animate-spin text-petrol" />
        ) : isError ? (
          <XCircleIcon className="size-3.5 text-destructive" />
        ) : elapsed != null ? (
          <span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
            {formatElapsed(elapsed)}
          </span>
        ) : undefined
      }
    >
      {subagent.taskInput && (
        <StepSection label="TASK">
          <StepCode value={subagent.taskInput} />
        </StepSection>
      )}
      {todos.length > 0 && <TodoList todos={todos} />}
      {messages.some(isAIMessage) && (
        <SubAgentConversation
          messages={messages}
          toolCalls={toolCalls}
          isStreaming={isStreaming}
          describe={describe}
        />
      )}
      {result != null && result !== "" && (
        <StepSection label="RESULT">
          <div className="min-w-0 rounded-[6px] border border-border bg-card px-3 py-2.5 text-[12.5px] leading-[1.6] text-body dark:text-panel-body">
            <MessageResponse className="text-[12.5px] leading-[1.6]">
              {result}
            </MessageResponse>
          </div>
        </StepSection>
      )}
      {isError && subagent.error != null && (
        <StepSection label="ERROR" error>
          <StepCode value={subagent.error} />
        </StepSection>
      )}
    </ChainStep>
  );
});

const isDone = (s: SubagentDiscoverySnapshot) =>
  s.status === "complete" || s.status === "error";

export const SubAgentProgress = memo(function SubAgentProgress({
  subagents,
}: {
  subagents: SubagentDiscoverySnapshot[];
}) {
  const total = subagents.length;
  if (total <= 1) return null;
  const completed = subagents.filter(isDone).length;

  return (
    <div className="flex items-center gap-2 font-mono text-[10.5px] text-meta dark:text-panel-dim">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-hover dark:bg-white/10">
        <div
          className="h-full rounded-full bg-petrol transition-all duration-300"
          style={{ width: `${(completed / total) * 100}%` }}
        />
      </div>
      <span>
        {completed}/{total} complete
      </span>
    </div>
  );
});

export const SynthesisIndicator = memo(function SynthesisIndicator({
  subagents,
  isCoordinatorStreaming,
}: {
  subagents: SubagentDiscoverySnapshot[];
  isCoordinatorStreaming: boolean;
}) {
  if (!isCoordinatorStreaming || subagents.length === 0 || !subagents.every(isDone)) {
    return null;
  }
  return (
    <div
      className={cn(
        "flex animate-pulse items-center gap-2 text-[12.5px] italic text-muted-foreground",
      )}
    >
      <Loader size={12} className="animate-spin" />
      Synthesizing results…
    </div>
  );
});

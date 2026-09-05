"use client";

import { Fragment, memo, useMemo, useState } from "react";
import { Loader2, XCircleIcon } from "lucide-react";
import { isAIMessage } from "@langchain/core/messages";
import type { BaseMessage } from "@langchain/core/messages";
import type { AnyStream, SubagentDiscoverySnapshot } from "@langchain/react";
import type { Interrupt } from "@langchain/langgraph-sdk";
import { Loader } from "@/components/ai-elements/loader";
import {
  ChainBand,
  ChainRail,
  ChainReasoningLine,
  ChainStep,
  NeedsApprovalBadge,
  StepCode,
  StepSection,
} from "@/components/ai-elements/chain-of-thought";
import {
  type HitlDecision,
  type HitlResponse,
  useHitlApprovals,
} from "@/hooks/use-hitl-approvals";
import {
  useSubagentMessages,
  useSubagentToolCalls,
  useSubagentValues,
} from "@/hooks/use-subagent-projections";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import { cn } from "@/lib/utils";
import {
  type ToolCallView,
  extractHitlToolNames,
  findSubagentInterrupt,
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
  isInterrupted,
  hitlToolNames,
  decisions,
  recordDecision,
  approvalsDisabled,
}: {
  messages: BaseMessage[];
  toolCalls: ToolCallView[];
  isStreaming: boolean;
  describe: DescribeTool;
  /** This subagent is paused on an approval. */
  isInterrupted: boolean;
  hitlToolNames: Set<string> | null;
  decisions: Partial<Record<string, HitlDecision>>;
  recordDecision: (toolCallId: string, decision: HitlDecision) => void;
  approvalsDisabled: boolean;
}) {
  const byMessage = new Map<string, ToolCallView[]>();
  for (const tc of toolCalls) {
    if (!tc.messageId) continue;
    byMessage.set(tc.messageId, [...(byMessage.get(tc.messageId) ?? []), tc]);
  }
  const last = messages.length - 1;

  return (
    <ChainRail startAtFirstNode>
      {messages.map((message, i) => {
        if (!isAIMessage(message)) return null;
        const text = message.text;
        const calls = message.id ? (byMessage.get(message.id) ?? []) : [];
        return (
          <Fragment key={message.id ?? i}>
            {text && (
              <ChainReasoningLine
                text={text}
                streaming={isStreaming && i === last && calls.length === 0}
              />
            )}
            {calls.map((tc) => {
              const state = getToolStepState(tc, isInterrupted, hitlToolNames);
              return (
                <ToolStep
                  key={tc.id}
                  tc={tc}
                  state={state}
                  describe={describe}
                  nested
                  approval={
                    state === "awaiting-approval"
                      ? {
                          decided: decisions[tc.id],
                          disabled: approvalsDisabled,
                          onDecide: (decision) => {
                            recordDecision(tc.id, decision);
                          },
                        }
                      : undefined
                  }
                />
              );
            })}
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
   *  (mount = subscribe, unmount = unsubscribe, resumed across runs); an idle
   *  thread's history is seeded by the SDK from `POST /threads/{id}/history`. */
  stream: AnyStream;
  describe: DescribeTool;
  /** The workspace agent behind this subagent, for its emoji/pastel tile. */
  agent?: { name: string; emoji?: string | null; color?: string | null };
  /** Interrupts raised inside subagents; the card claims its own. */
  interrupts: readonly Interrupt[];
  /** Resume — `stream.respond(response, { interruptId })`. */
  respond: (response: HitlResponse, interruptId: string | null) => void;
  /** A run is executing; approvals are held until it settles. */
  resumeInFlight: boolean;
  modelUnavailable: boolean;
};

export const SubAgentCard = memo(function SubAgentCard({
  subagent,
  stream,
  describe,
  agent,
  interrupts,
  respond,
  resumeInFlight,
  modelUnavailable,
}: SubAgentCardProps) {
  const { status, startedAt, completedAt } = subagent;
  // Scoped projections that keep flowing across a HITL pause (the SDK's own
  // end at the first terminal lifecycle — see the hook module).
  const messages = useSubagentMessages(stream, subagent);
  const liveToolCalls = useSubagentToolCalls(stream, subagent);
  const values = useSubagentValues(stream, subagent);
  const toolCalls = useMemo(
    () => pairToolCalls(messages, liveToolCalls),
    [messages, liveToolCalls],
  );

  // A subagent's gated tool pauses the whole run on an interrupt raised in
  // its namespace. The SDK has no "paused" status for it (the `task` call
  // is still running), so the card derives one from the interrupt it owns
  // and approves it in place — same collector as the root chain, one batch
  // per interrupt id, resumed through `input.respond`.
  const interrupt = useMemo(
    () => findSubagentInterrupt(interrupts, subagent),
    [interrupts, subagent],
  );
  const isInterrupted = interrupt != null;
  const hitlToolNames = useMemo(
    () => extractHitlToolNames(interrupt?.value),
    [interrupt],
  );
  const pendingToolCalls = useMemo(
    () =>
      toolCalls.filter(
        (tc) =>
          getToolStepState(tc, isInterrupted, hitlToolNames) ===
          "awaiting-approval",
      ),
    [toolCalls, isInterrupted, hitlToolNames],
  );
  // Calls persisted without an id can only be resumed positionally.
  const pendingIdsAreReal = pendingToolCalls.every((tc) => tc.callId != null);
  // Parallel subagents can pause together, each with its own interrupt;
  // the thread runs one resume at a time, so a completed batch waits for
  // the run in flight to settle and is sent when its interrupt still pends.
  const { decisions, recordDecision } = useHitlApprovals({
    interruptId: pendingIdsAreReal ? (interrupt?.id ?? null) : null,
    pendingToolCalls,
    respond,
    enabled: !resumeInFlight,
  });
  const awaitingDecision = pendingToolCalls.some((tc) => !decisions[tc.id]);

  const isStreaming = status === "running" && !isInterrupted;
  const isError = status === "error";
  const todos = (values?.todos ?? []) as Todo[];
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
        // Same 22px square as the other rail nodes. The pastel is translucent
        // (~8% alpha), so an opaque card layer sits under it to hide the rail.
        <span className="relative z-[1] flex size-[22px] shrink-0 rounded-[6px] bg-card">
          <AgentAvatar
            color={agent?.color}
            emoji={agent?.emoji}
            size="2xs"
            shape="tile"
          />
        </span>
      }
      title={`Ask ${agent?.name ?? subagent.name.replaceAll("_", " ")}`}
      summary={subagent.taskInput}
      lockOpen={autoOpen || (isInterrupted && awaitingDecision)}
      onOpenChange={() => {
        setAutoOpen(false);
      }}
      meta={
        isInterrupted ? (
          <NeedsApprovalBadge />
        ) : isStreaming ? (
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
      <ChainBand label="TASK" text={subagent.taskInput}>
        {todos.length > 0 && <TodoList todos={todos} className="mb-3" />}
        <SubAgentConversation
          messages={messages}
          toolCalls={toolCalls}
          isStreaming={isStreaming}
          describe={describe}
          isInterrupted={isInterrupted}
          hitlToolNames={hitlToolNames}
          decisions={decisions}
          recordDecision={recordDecision}
          approvalsDisabled={modelUnavailable}
        />
        {isError && subagent.error != null && (
          <StepSection label="ERROR" error className="mt-2">
            <StepCode value={subagent.error} />
          </StepSection>
        )}
      </ChainBand>
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

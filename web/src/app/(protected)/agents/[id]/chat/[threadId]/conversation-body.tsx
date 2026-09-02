"use client";

import { Fragment, memo, useCallback, useMemo, useRef, useState } from "react";
import Image from "next/image";
import {
  MessageActions,
  MessageAction,
  Message,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import {
  Reasoning,
  ReasoningTrigger,
  ReasoningContent,
} from "@/components/ai-elements/reasoning";
import {
  ChainOfThought,
  ChainStep,
  ChainStepIcon,
  NeedsApprovalBadge,
  StepCode,
  StepSection,
  TERMINAL_ICON,
  humanizeToolName,
  isSandboxTool,
  summarizeToolArgs,
} from "@/components/ai-elements/chain-of-thought";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import {
  Error,
  ErrorContent,
  ErrorDetails,
} from "@/components/ai-elements/error";
import {
  Attachment,
  AttachmentPreview,
  AttachmentHoverCard,
  AttachmentHoverCardTrigger,
  AttachmentInfo,
  AttachmentHoverCardContent,
  getMediaCategory,
  getAttachmentLabel,
  Attachments,
} from "@/components/ai-elements/attachments";
import {
  SubAgentCard,
  SubAgentProgress,
  SynthesisIndicator,
} from "@/components/ai-elements/subagent";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import { extractToolErrorText } from "@/lib/utils/tool-content";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useAgentsStore } from "@/stores/agents-store";
import type { HitlDecision } from "@/hooks/use-hitl-approvals";
import {
  RefreshCcwIcon,
  CopyIcon,
  Loader2,
  XCircleIcon,
} from "lucide-react";
import { ThinkingLoader } from "../components/loader";
import { McpAppWidget } from "../components/mcp-app-widget";
import {
  type ChainStepData,
  type LCMessage,
  type LocalToolCall,
  type SubagentData,
  getFileAttachments,
  getMcpAppInfoFromToolCall,
  getReasoningContent,
  getStructuredContentFromToolCall,
  getTextContent,
  getToolMetadata,
  getToolOutputContent,
  getToolRenderState,
  sanitizeToolIdentifier,
} from "./message-helpers";

export type ConversationBodyProps = {
  threadId: string;
  /** Throttled stream messages (or initial history when idle). */
  messages: LCMessage[];
  /** Tool calls derived (memoized) from `messages`. */
  toolCalls: LocalToolCall[];
  /** Stable wrapper around the SDK's subagent lookup. */
  getSubagentsByMessage: (messageId: string) => SubagentData[];
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
  /**
   * Bumped (throttled, ~16Hz) on stream notifications that change no other
   * prop — subagent token streams only mutate SDK-internal state — so this
   * memoized body still re-renders to show them. Not read; its only job is
   * to break the memo comparison.
   */
  streamTick: number;
};

/**
 * The conversation render tree, extracted from ChatPage and memoized so the
 * component that owns `useStream` (notified per SSE event) renders almost
 * nothing itself. All props are either throttled (~16Hz) or identity-stable
 * between stream events, which bounds how often this (large) tree rebuilds.
 */
export const ConversationBody = memo(function ConversationBody({
  threadId,
  messages,
  toolCalls,
  getSubagentsByMessage,
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

  // Subagent internal conversations restored from subgraph checkpoints on
  // refresh, keyed by tool_call_id. The SDK's custom transport doesn't expose a
  // way to inject these into the reconstructed subagents, so we hold them here
  // and pass them to SubAgentCard as a fallback.
  const [subagentMessages, setSubagentMessages] = useState<
    Record<string, unknown[]>
  >({});
  const fetchedSubagentHistory = useRef(new Set<string>());

  const loadSubagentHistory = useCallback(
    async (toolCallId: string) => {
      const key = `${threadId}:${toolCallId}`;
      if (fetchedSubagentHistory.current.has(key)) return;
      fetchedSubagentHistory.current.add(key);

      try {
        const res = await api.get(
          `/threads/${threadId}/subagents/${toolCallId}/state`,
        );
        const msgs = res.data?.messages;
        if (Array.isArray(msgs) && msgs.length > 0) {
          setSubagentMessages((prev) => ({ ...prev, [toolCallId]: msgs }));
        }
      } catch {
        // Allow a later open to retry a transient failure.
        fetchedSubagentHistory.current.delete(key);
      }
    },
    [threadId],
  );

  const knownServerNames = useMemo(
    () =>
      [...mcpServers.map((server) => server.name)].sort(
        (a, b) => b.length - a.length,
      ),
    [mcpServers],
  );

  // Resolve a subagent_type (sanitize_tool_name(agent.name) backend-side)
  // back to the workspace agent, for its emoji/pastel tile in chain steps.
  const findAgentForSubagentType = useCallback(
    (subagentType: string | undefined) => {
      if (!subagentType) return undefined;
      return (
        workspaceAgents.find(
          (a) => sanitizeToolIdentifier(a.name) === subagentType,
        ) ??
        workspaceAgents.find(
          (a) =>
            a.name.toLowerCase() ===
            subagentType.replaceAll("_", " ").toLowerCase(),
        )
      );
    },
    [workspaceAgents],
  );

  // Index tool calls by AI message id once per render, so the inner map can
  // look them up in O(1) instead of filtering the full list per message.
  const toolCallsByMessageId = useMemo(() => {
    const map = new Map<string, LocalToolCall[]>();
    for (const tc of toolCalls) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const id = (tc.aiMessage as any)?.id as string | undefined;
      if (!id || !tc.call.name) continue;
      const existing = map.get(id);
      if (existing) existing.push(tc);
      else map.set(id, [tc]);
    }
    return map;
  }, [toolCalls]);

  const getToolCallsForMessage = useCallback(
    (message: LCMessage) => {
      if (!message.id) return [];
      return toolCallsByMessageId.get(message.id) ?? [];
    },
    [toolCallsByMessageId],
  );

  // Loading state detection
  const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
  const isAwaitingResponse =
    isLoading &&
    lastMsg != null &&
    (lastMsg.type === "human" || lastMsg.type === "user");

  const assistantIsStreaming =
    isLoading &&
    lastMsg != null &&
    (lastMsg.type === "ai" || lastMsg.type === "assistant");

  // ---- Chain-of-thought grouping ----
  // One timeline per run of *consecutive* tool work: steps from adjacent AI
  // messages merge into the run's first step-bearing AI message, but any
  // assistant text ends the run — a message's own steps render above its
  // text, and tool calls after the text start a new chain below it. Task
  // tool calls pair with their SDK subagent stream by id, preserving the
  // original tool_call order.
  const chainByOwner = new Map<string, ChainStepData[]>();
  {
    let turnOwner: string | null = null;
    for (const m of messages) {
      if (m.type === "human" || m.type === "user") {
        turnOwner = null;
        continue;
      }
      if ((m.type !== "ai" && m.type !== "assistant") || !m.id) continue;
      const hasText = getTextContent(m).trim().length > 0;
      const tcs = getToolCallsForMessage(m);
      const subs = getSubagentsByMessage(m.id);
      if (tcs.length === 0 && subs.length === 0) {
        if (hasText) turnOwner = null;
        continue;
      }

      const subById = new Map(subs.map((s) => [s.id, s]));
      const paired = new Set<string>();
      const steps: ChainStepData[] = [];
      for (const tc of tcs) {
        const sub = subById.get(tc.id);
        if (sub) {
          steps.push({ kind: "subagent", sub });
          paired.add(sub.id);
        } else {
          steps.push({ kind: "tool", tc });
        }
      }
      for (const sub of subs) {
        if (!paired.has(sub.id)) steps.push({ kind: "subagent", sub });
      }

      if (turnOwner == null) {
        turnOwner = m.id;
        chainByOwner.set(m.id, steps);
      } else {
        chainByOwner.get(turnOwner)?.push(...steps);
      }
      // The message's text renders below its steps — anything after it
      // belongs to a fresh chain.
      if (hasText) turnOwner = null;
    }
  }

  // ---- Render ----

  return (
    <>
      {supervisorTodos.length > 0 && (
        <TodoList
          todos={supervisorTodos}
          className="mb-4 rounded-lg border border-border/50 bg-muted/30 p-4"
        />
      )}
      {messages.map((message, messageIndex) => {
        // Skip tool messages — they're rendered via toolCalls pairing
        if (message.type === "tool") return null;

        // ---- Human message ----
        if (message.type === "human" || message.type === "user") {
          const text = getTextContent(message);
          const attachments = getFileAttachments(message);

          return (
            <Fragment key={message.id ?? messageIndex}>
              {attachments.length > 0 && (
                <div className="flex justify-end">
                  <Attachments variant="inline">
                    {attachments.map((attachment) => {
                      const mediaCategory = getMediaCategory(attachment);
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
                              {mediaCategory === "image" &&
                                "url" in attachment &&
                                attachment.url && (
                                  <div className="flex items-center justify-center overflow-hidden rounded-md border">
                                    <Image
                                      alt={label}
                                      className="object-contain"
                                      height={200}
                                      src={attachment.url as string}
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
            </Fragment>
          );
        }

        // ---- AI message ----
        if (message.type === "ai" || message.type === "assistant") {
          const text = getTextContent(message);
          const reasoning = getReasoningContent(message);
          const chainSteps = message.id
            ? (chainByOwner.get(message.id) ?? [])
            : [];
          const chainSubagents = chainSteps
            .filter(
              (s): s is Extract<ChainStepData, { kind: "subagent" }> =>
                s.kind === "subagent",
            )
            .map((s) => s.sub);
          const chainActive = chainSteps.some((s) =>
            s.kind === "tool"
              ? s.tc.state === "pending"
              : s.sub.status === "running" || s.sub.status === "pending",
          );
          const chainLockOpen = chainSteps.some(
            (s) =>
              s.kind === "tool" &&
              getToolRenderState(s.tc, isInterrupted, hitlToolNames) ===
                "approval-requested" &&
              !decisions[s.tc.id],
          );
          const isTaskCall = (tc: LocalToolCall) => tc.call.name === "task";
          const toolCount = chainSteps.filter(
            (s) => s.kind === "tool" && !isTaskCall(s.tc),
          ).length;
          const subagentCount = chainSteps.length - toolCount;
          // Last visible message: nothing after it, or only tool results
          // (tool messages render via the chain, not as bubbles — parallel
          // tool calls can leave several of them trailing).
          const isLastMessage =
            messageIndex === messages.length - 1 ||
            messages.slice(messageIndex + 1).every((m) => m.type === "tool");
          const isLastAiMessage = !isLoading && isLastMessage && text.length > 0;

          return (
            <Fragment key={message.id ?? messageIndex}>
              {/* Reasoning / thinking */}
              {reasoning && (
                <Reasoning
                  className="w-full"
                  isStreaming={assistantIsStreaming && isLastMessage}
                >
                  <ReasoningTrigger />
                  <ReasoningContent>{reasoning}</ReasoningContent>
                </Reasoning>
              )}

              {/* Chain of thought: the turn's tool + subagent steps */}
              {chainSteps.length > 0 && (
                <div className="w-full space-y-2">
                  <ChainOfThought
                    active={chainActive}
                    lockOpen={chainLockOpen}
                    toolCount={toolCount}
                    subagentCount={subagentCount}
                  >
                    {chainSteps.map((step) => {
                      if (step.kind === "subagent") {
                        const sub = step.sub;
                        return (
                          <SubAgentCard
                            key={sub.id}
                            subagent={sub}
                            mcpServers={mcpServers}
                            agent={findAgentForSubagentType(
                              (
                                sub.toolCall as
                                  | { args?: Record<string, unknown> }
                                  | undefined
                              )?.args?.subagent_type as string | undefined,
                            )}
                            onOpen={
                              sub.messages.length === 0 &&
                              (sub.status === "complete" ||
                                sub.status === "error")
                                ? () => void loadSubagentHistory(sub.id)
                                : undefined
                            }
                            fallbackMessages={subagentMessages[sub.id]}
                          />
                        );
                      }

                      const tc = step.tc;
                      const toolState = getToolRenderState(
                        tc,
                        isInterrupted,
                        hitlToolNames,
                      );
                      const decided = decisions[tc.id];
                      const output = getToolOutputContent(tc);
                      const errorText =
                        tc.state === "error" && tc.result
                          ? extractToolErrorText(tc.result.content)
                          : undefined;
                      const stepMeta =
                        toolState === "approval-requested" ? (
                          <NeedsApprovalBadge />
                        ) : toolState === "input-available" ? (
                          <Loader2 className="size-3 animate-spin text-petrol" />
                        ) : toolState === "output-error" ? (
                          <XCircleIcon className="size-3.5 text-destructive" />
                        ) : undefined;
                      const approvalFooter =
                        toolState === "approval-requested" ? (
                          <div className="flex items-center gap-2 pt-1">
                            <button
                              type="button"
                              disabled={decided != null || modelUnavailable}
                              onClick={() => {
                                recordDecision(tc.id, "approve");
                              }}
                              className={cn(
                                "cursor-pointer rounded-[7px] bg-petrol px-4 py-1.5 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed",
                                decided === "reject" && "opacity-40",
                              )}
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              disabled={decided != null || modelUnavailable}
                              onClick={() => {
                                recordDecision(tc.id, "reject");
                              }}
                              className={cn(
                                "cursor-pointer rounded-[7px] border border-input bg-card px-4 py-1.5 text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover disabled:cursor-not-allowed",
                                decided === "approve" && "opacity-40",
                              )}
                            >
                              Deny
                            </button>
                          </div>
                        ) : null;
                      const resultSection =
                        errorText !== undefined ? (
                          <StepSection label="ERROR" error>
                            <StepCode value={errorText} />
                          </StepSection>
                        ) : (
                          output !== undefined && (
                            <StepSection label="RESULT">
                              <StepCode value={output} />
                            </StepSection>
                          )
                        );

                      if (isTaskCall(tc)) {
                        // task call the SDK didn't pair with a subagent
                        // stream (e.g. filtered history) — still render
                        // it as a subagent-style step.
                        const args = tc.call.args as
                          | Record<string, unknown>
                          | undefined;
                        const subagentType = (args?.subagent_type ??
                          args?.subagentType) as string | undefined;
                        const matched = findAgentForSubagentType(subagentType);
                        const description = args?.description as
                          | string
                          | undefined;
                        return (
                          <ChainStep
                            key={tc.id}
                            node={
                              <AgentAvatar
                                color={matched?.color}
                                emoji={matched?.emoji}
                                size="2xs"
                                className="relative z-[1]"
                              />
                            }
                            title={`Ask ${matched?.name ?? subagentType?.replaceAll("_", " ") ?? "subagent"}`}
                            summary={description}
                            meta={stepMeta}
                            lockOpen={
                              toolState === "approval-requested" && !decided
                            }
                          >
                            {description && (
                              <StepSection label="TASK">
                                <StepCode value={description} />
                              </StepSection>
                            )}
                            {resultSection}
                            {approvalFooter}
                          </ChainStep>
                        );
                      }

                      const sandbox = isSandboxTool(tc.call.name);
                      const { serverName, toolName } = sandbox
                        ? {
                            serverName: "Code execution",
                            toolName: tc.call.name,
                          }
                        : getToolMetadata(tc.call.name, knownServerNames);
                      return (
                        <ChainStep
                          key={tc.id}
                          node={
                            <ChainStepIcon
                              icon={
                                sandbox
                                  ? TERMINAL_ICON
                                  : mcpServers.find(
                                      (server) => server.name === serverName,
                                    )?.iconUrl
                              }
                              name={serverName}
                            />
                          }
                          title={humanizeToolName(toolName)}
                          summary={summarizeToolArgs(tc.call.args)}
                          meta={stepMeta}
                          lockOpen={
                            toolState === "approval-requested" && !decided
                          }
                        >
                          {tc.call.args !== undefined && (
                            <StepSection label="PARAMETERS">
                              <StepCode value={tc.call.args} />
                            </StepSection>
                          )}
                          {resultSection}
                          {approvalFooter}
                        </ChainStep>
                      );
                    })}
                  </ChainOfThought>
                  {chainSubagents.length > 0 && (
                    <>
                      <SubAgentProgress subagents={chainSubagents} />
                      <SynthesisIndicator
                        subagents={chainSubagents}
                        isCoordinatorStreaming={
                          assistantIsStreaming && isLastMessage
                        }
                      />
                    </>
                  )}
                  {/* Interactive MCP app widgets surface below the chain */}
                  {chainSteps.map((step) => {
                    if (step.kind !== "tool") return null;
                    const appToolInfo = getMcpAppInfoFromToolCall(step.tc);
                    if (!appToolInfo) return null;
                    return (
                      <McpAppWidget
                        key={`app-${step.tc.id}`}
                        input={step.tc.call.args}
                        output={getToolOutputContent(step.tc)}
                        structuredContent={getStructuredContentFromToolCall(
                          step.tc,
                        )}
                        errorText={
                          step.tc.state === "error" && step.tc.result
                            ? extractToolErrorText(step.tc.result.content)
                            : undefined
                        }
                        toolName={
                          getToolMetadata(step.tc.call.name, knownServerNames)
                            .toolName
                        }
                        appToolInfo={appToolInfo}
                      />
                    );
                  })}
                </div>
              )}

              {/* Text content */}
              {text && (
                <>
                  <Message from="assistant">
                    <MessageContent>
                      <MessageResponse>{text}</MessageResponse>
                    </MessageContent>
                  </Message>
                  {isLastAiMessage && (
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
        }

        return null;
      })}

      {/* Loading indicator */}
      {isAwaitingResponse && (
        <div>
          <Message from="assistant">
            <div className="w-full flex flex-col gap-2">
              <MessageContent>
                <ThinkingLoader className="px-0" />
              </MessageContent>
            </div>
          </Message>
        </div>
      )}

      {/* Streaming indicator when AI has started but text is still coming */}
      {assistantIsStreaming &&
        getTextContent(lastMsg).length === 0 &&
        !getToolCallsForMessage(lastMsg).length && (
          <div>
            <Message from="assistant">
              <div className="w-full flex flex-col gap-2">
                <MessageContent>
                  <ThinkingLoader className="px-0" />
                </MessageContent>
              </div>
            </Message>
          </div>
        )}

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

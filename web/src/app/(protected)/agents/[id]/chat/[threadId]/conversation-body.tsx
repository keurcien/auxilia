"use client";

import {
  Fragment,
  memo,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import Image from "next/image";
import type { BaseMessage } from "@langchain/core/messages";
import {
  isAIMessage,
  isHumanMessage,
  isToolMessage,
} from "@langchain/core/messages";
import type { AnyStream, SubagentDiscoverySnapshot } from "@langchain/react";
import type { Interrupt } from "@langchain/langgraph-sdk";
import {
  ChevronDownIcon,
  Clock3Icon,
  CopyIcon,
  DownloadIcon,
  ExternalLinkIcon,
  MessagesSquareIcon,
  PaperclipIcon,
  RefreshCcwIcon,
} from "lucide-react";
import { FileIcon } from "@/components/artifacts/file-type-icon";
import { SlackLogo } from "@/components/slack-logo";
import { TelegramLogo } from "@/components/telegram-logo";
import { WhatsAppLogo } from "@/components/whatsapp-logo";
import {
  Message,
  MessageAction,
  MessageActions,
  MessageContent,
  MessageResponse,
} from "@/components/ai-elements/message";
import { Loader } from "@/components/ai-elements/loader";
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
  type AttachmentData,
} from "@/components/ai-elements/attachments";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useAgentsStore } from "@/stores/agents-store";
import * as agentsApi from "@/lib/api/resources/agents";
import type { HitlDecision, HitlResponse } from "@/hooks/use-hitl-approvals";
import type { AgentResourceSandbox } from "@/types/agents";
import type { QueuedPrompt, Run } from "@/types/runs";
import {
  AppSlot,
  ArtifactCards,
  useAttachedFiles,
} from "@/components/artifacts/workspace";
import { contentUrl } from "@/lib/api/resources/artifacts";
import {
  type ChainStepData,
  type ToolCallView,
  type ToolStepState,
  getAttachmentIds,
  getFileAttachments,
  getMcpAppInfo,
  getReasoning,
  getStructuredContent,
  getToolStepState,
  groupChains,
  sanitizeToolIdentifier,
  claimsInterrupt,
} from "@/lib/transcript";
import {
  presentSideChannelMessage,
  type SideChannelContextMessage,
} from "@/lib/transcript/side-channel-context";
import {
  SubAgentCard,
  SubAgentProgress,
  SynthesisIndicator,
} from "./subagent-card";
import { threadMapAnchor } from "@/components/ai-elements/thread-map";
import { type DescribeTool, ToolStep, useDescribeTool } from "./tool-step";

export type ConversationBodyProps = {
  agentId: string;
  /** Throttled `stream.messages` (or the hydrated history when idle). */
  messages: BaseMessage[];
  /** Durable run history used to display each prompt's response time. */
  runs: Run[];
  /** `pairToolCalls(messages, stream.toolCalls)`, memoized by the page. */
  toolCalls: ToolCallView[];
  /** `stream.subagents` — discovery snapshots keyed by `task` tool-call id. */
  subagents: ReadonlyMap<string, SubagentDiscoverySnapshot>;
  /** Identity-stable stream handle for the cards' scoped subscriptions. */
  stream: AnyStream;
  supervisorTodos: Todo[];
  isLoading: boolean;
  /** Local submit sent, before the server stream reports the active run. */
  isStarting: boolean;
  isInterrupted: boolean;
  hitlToolNames: Set<string> | null;
  decisions: Partial<Record<string, HitlDecision>>;
  recordDecision: (toolCallId: string, decision: HitlDecision) => void;
  /** Interrupts raised inside subagents (`stream.interrupts` minus the root
   *  one); each card claims its own and approves it itself. */
  nestedInterrupts: Interrupt[];
  /** Resume an interrupt — `stream.respond(response, { interruptId })`. */
  respond: (
    response: HitlResponse,
    interruptId: string | null,
  ) => Promise<void>;
  modelUnavailable: boolean;
  readOnly: boolean;
  onRegenerate: () => void;
  /** A claimed queued prompt waiting for its server-authored message event. */
  optimisticPrompt: QueuedPrompt | null;
  /** The title retained by a legacy thread whose first run never persisted. */
  emptyPrompt: string | null;
  /** The empty transcript belongs to a failed run whose full input is durable. */
  canRetryInitial: boolean;
  showEmptyState: boolean;
  onRetryInitialPrompt: () => void;
  hydrationError: unknown;
  onRetryHydration: () => void;
  error: unknown;
  rehydratedError: string | null;
};

function errorDetail(error: unknown, rehydratedError: string | null) {
  if (error != null) {
    return error instanceof globalThis.Error ? error.message : String(error);
  }
  return rehydratedError;
}

function userTurnKey(message: BaseMessage, index: number) {
  return message.id != null ? `message:${message.id}` : `index:${index}`;
}

/**
 * The conversation render tree, memoized so the page that owns `useStream`
 * (notified on every store tick) renders almost nothing itself. Every prop is
 * either throttled or identity-stable between ticks.
 */
export const ConversationBody = memo(function ConversationBody({
  agentId,
  messages,
  runs,
  toolCalls,
  subagents,
  stream,
  supervisorTodos,
  isLoading,
  isStarting,
  isInterrupted,
  hitlToolNames,
  decisions,
  recordDecision,
  nestedInterrupts,
  respond,
  modelUnavailable,
  readOnly,
  onRegenerate,
  optimisticPrompt,
  emptyPrompt,
  canRetryInitial,
  showEmptyState,
  onRetryInitialPrompt,
  hydrationError,
  onRetryHydration,
  error,
  rehydratedError,
}: ConversationBodyProps) {
  const { mcpServers } = useMcpServersStore();
  const workspaceAgents = useAgentsStore((s) => s.agents);
  const [sandboxIdentity, setSandboxIdentity] = useState<{
    agentId: string;
    sandbox: AgentResourceSandbox | undefined;
  } | null>(null);
  const sandbox =
    sandboxIdentity?.agentId === agentId ? sandboxIdentity.sandbox : undefined;
  const describe = useDescribeTool(mcpServers, sandbox);

  useEffect(() => {
    let active = true;
    void agentsApi
      .getAgentResources(agentId)
      .then((resources) => {
        if (active) {
          setSandboxIdentity({
            agentId,
            sandbox: resources.sandboxes[0],
          });
        }
      })
      .catch(() => {
        if (active) setSandboxIdentity({ agentId, sandbox: undefined });
      });
    return () => {
      active = false;
    };
  }, [agentId]);

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
  const todosByUserTurn = useMemo(
    () => mapTodosToUserTurns(messages, toolCalls, supervisorTodos),
    [messages, toolCalls, supervisorTodos],
  );
  const runMetadataByUserTurn = useMemo(
    () => mapRunMetadataToUserTurns(messages, runs),
    [messages, runs],
  );
  const [errorsByUserTurn, setErrorsByUserTurn] = useState<
    Readonly<Record<string, string>>
  >({});
  const latestUserIndex = messages.findLastIndex(
    (message) => isHumanMessage(message) && !isHostNotice(message),
  );
  const latestUserKey =
    latestUserIndex >= 0
      ? userTurnKey(messages[latestUserIndex], latestUserIndex)
      : null;
  const currentErrorDetail = errorDetail(error, rehydratedError);
  // useStream retains the previous run's error while the next run starts.
  // Record errors only once a run is idle so that stale errors cannot move
  // from the turn that failed to the newly submitted user message.
  if (
    !isLoading &&
    latestUserKey != null &&
    currentErrorDetail != null &&
    errorsByUserTurn[latestUserKey] !== currentErrorDetail
  ) {
    setErrorsByUserTurn({
      ...errorsByUserTurn,
      [latestUserKey]: currentErrorDetail,
    });
  }

  const lastVisibleIndex = messages.findLastIndex((m) => !isToolMessage(m));
  const lastVisible =
    lastVisibleIndex >= 0 ? messages[lastVisibleIndex] : undefined;
  const assistantStreaming =
    isLoading && lastVisible != null && isAIMessage(lastVisible);
  // The assistant has started a message but produced no text or tool call
  // yet: its reasoning is what's streaming.
  const preamble =
    assistantStreaming &&
    lastVisible.text.length === 0 &&
    !toolCalls.some((tc) => tc.messageId === lastVisible.id);
  const reasoningStreamingId =
    preamble && getReasoning(lastVisible) ? (lastVisible.id ?? null) : null;
  // "Thinking…" until anything at all arrives.
  const showThinking =
    isLoading &&
    (isStarting ||
      (lastVisible != null &&
        (isHumanMessage(lastVisible) ||
          (preamble && reasoningStreamingId == null))));
  const pendingUserIndex =
    showThinking && optimisticPrompt == null
      ? messages.findLastIndex(
          (message) => isHumanMessage(message) && !isHostNotice(message),
        )
      : -1;

  return (
    <>
      {messages.map((message, index) => {
        const key = message.id ?? index;
        if (isHumanMessage(message)) {
          const runMetadata = runMetadataByUserTurn.get(
            userTurnKey(message, index),
          );
          // Host notices are context for the model; the chat already shows the files.
          return isHostNotice(message) ? null : (
            <UserTurn
              key={key}
              message={message}
              anchorId={threadMapAnchor(index)}
              sending={index === pendingUserIndex}
              todos={todosByUserTurn.get(key)}
              durationMs={runMetadata?.durationMs}
              promptedAt={runMetadata?.promptedAt}
              error={errorsByUserTurn[userTurnKey(message, index)]}
            />
          );
        }
        if (!isAIMessage(message)) return null;

        const text = message.text;
        const sources = getWebSearchSources(message);
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
                resumeInFlight={isLoading}
                modelUnavailable={modelUnavailable}
                coordinatorStreaming={assistantStreaming && isLast}
              />
            )}
            {text && (
              <>
                <Message from="assistant">
                  <MessageContent>
                    <MessageResponse>{text}</MessageResponse>
                    {sources.length > 0 && (
                      <WebSearchSources sources={sources} />
                    )}
                  </MessageContent>
                </Message>
                {!isLoading && isLast && (
                  <MessageActions>
                    {!modelUnavailable && !readOnly && (
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

      {hydrationError != null && (
        <div className="mx-auto flex w-full max-w-xl flex-col gap-3 rounded-lg border border-destructive/30 bg-destructive/10 p-4">
          <p className="text-sm font-medium text-destructive">
            Conversation history could not be loaded.
          </p>
          <p className="text-xs text-destructive">
            {hydrationError instanceof globalThis.Error
              ? hydrationError.message
              : String(hydrationError)}
          </p>
          <button
            type="button"
            className="w-fit shrink-0 cursor-pointer whitespace-nowrap rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium hover:bg-muted"
            onClick={onRetryHydration}
          >
            Retry loading history
          </button>
        </div>
      )}

      {showEmptyState && messages.length === 0 && !isLoading && (
        <div className="mx-auto flex w-full max-w-xl flex-col gap-3 rounded-lg border border-border bg-muted/30 p-4">
          <p className="text-sm font-medium text-foreground">
            {canRetryInitial
              ? "The first response failed before any messages were saved."
              : emptyPrompt
                ? "This conversation's first message was not saved."
                : "This conversation has no saved messages."}
          </p>
          {emptyPrompt && (
            <p className="line-clamp-3 whitespace-pre-wrap text-sm text-muted-foreground">
              {emptyPrompt}
            </p>
          )}
          {currentErrorDetail && (
            <p className="text-xs text-destructive">{currentErrorDetail}</p>
          )}
          {!readOnly && (emptyPrompt || canRetryInitial) && (
            <button
              type="button"
              className="w-fit shrink-0 cursor-pointer whitespace-nowrap rounded-md border border-input bg-background px-3 py-1.5 text-sm font-medium hover:bg-muted"
              onClick={onRetryInitialPrompt}
            >
              Retry original message
            </button>
          )}
        </div>
      )}

      {optimisticPrompt && <OptimisticUserTurn prompt={optimisticPrompt} />}

      {showThinking && pendingUserIndex < 0 && optimisticPrompt == null && (
        <ChainThinking />
      )}
    </>
  );
});

/**
 * A user-role message the runtime authored, not the user: it carries
 * `name: "host"` and `additional_kwargs.host_notice` (e.g. the sandbox of
 * the thread was replaced). Context for the model, not shown in the chat.
 */
export function isHostNotice(message: BaseMessage): boolean {
  return (
    message.name === "host" &&
    typeof message.additional_kwargs?.host_notice === "string"
  );
}

type WebSearchSource = {
  url: string;
  title: string;
};

const SOURCE_HINT = /(annotation|citation|grounding|search|source)/i;

function getWebSearchSources(message: BaseMessage): WebSearchSource[] {
  const sources = new Map<string, WebSearchSource>();
  const seen = new WeakSet<object>();

  const visit = (value: unknown, hinted = false) => {
    if (Array.isArray(value)) {
      value.forEach((item) => {
        visit(item, hinted);
      });
      return;
    }
    if (value === null || typeof value !== "object") return;
    if (seen.has(value)) return;
    seen.add(value);

    const record = value as Record<string, unknown>;
    const typeHint =
      typeof record.type === "string" && SOURCE_HINT.test(record.type);
    const nextHint = hinted || typeHint;
    const candidate =
      typeof record.url === "string"
        ? record.url
        : typeof record.uri === "string"
          ? record.uri
          : null;

    if (candidate && nextHint) {
      try {
        const url = new URL(candidate);
        if (url.protocol === "https:" || url.protocol === "http:") {
          const title =
            typeof record.title === "string" && record.title.trim()
              ? record.title.trim()
              : url.hostname.replace(/^www\./, "");
          sources.set(url.href, { url: url.href, title });
        }
      } catch {
        // Ignore malformed provider metadata rather than rendering unsafe links.
      }
    }

    for (const [key, child] of Object.entries(record)) {
      visit(child, nextHint || SOURCE_HINT.test(key));
    }
  };

  visit(message.content);
  visit(message.additional_kwargs);
  visit(message.response_metadata);
  return [...sources.values()];
}

const WebSearchSources = ({ sources }: { sources: WebSearchSource[] }) => (
  <div className="mt-1 flex flex-wrap items-center gap-1.5">
    <span className="mr-0.5 text-[10.5px] font-medium text-meta dark:text-panel-dim">
      Sources
    </span>
    {sources.map((source) => (
      <a
        key={source.url}
        href={source.url}
        target="_blank"
        rel="noreferrer"
        className="inline-flex max-w-52 items-center gap-1 truncate rounded-md border border-border/70 bg-card px-2 py-1 text-[10.5px] font-medium text-body transition-colors hover:border-border-hover hover:text-petrol dark:bg-panel dark:text-panel-body dark:hover:text-panel-terminal"
        title={source.title}
      >
        <span className="truncate">{source.title}</span>
        <ExternalLinkIcon className="size-2.5 shrink-0" />
      </a>
    ))}
  </div>
);

/**
 * `todos` is a single graph-state channel, so rendering it globally detaches
 * the plan from the prompt that caused it. Persisted `write_todos` calls keep
 * every turn's snapshots: the last call in a turn is that prompt's final list.
 * The live channel then refreshes only the most recent turn that owns a list.
 */
function mapTodosToUserTurns(
  messages: readonly BaseMessage[],
  toolCalls: readonly ToolCallView[],
  latestTodos: Todo[],
): Map<string | number, Todo[]> {
  const callsByMessage = new Map<string, ToolCallView[]>();
  for (const toolCall of toolCalls) {
    if (!toolCall.messageId) continue;
    const calls = callsByMessage.get(toolCall.messageId);
    if (calls) calls.push(toolCall);
    else callsByMessage.set(toolCall.messageId, [toolCall]);
  }

  const todosByUserTurn = new Map<string | number, Todo[]>();
  let currentUserTurn: string | number | null = null;
  let latestTodoTurn: string | number | null = null;

  messages.forEach((message, index) => {
    const key = message.id ?? index;
    if (isHumanMessage(message)) {
      if (!isHostNotice(message)) currentUserTurn = key;
      return;
    }
    if (!isAIMessage(message) || !message.id || currentUserTurn == null) return;

    for (const toolCall of callsByMessage.get(message.id) ?? []) {
      if (toolCall.name !== "write_todos") continue;
      const todos = parseTodos(toolCall.args?.todos);
      if (todos == null) continue;
      todosByUserTurn.set(currentUserTurn, todos);
      latestTodoTurn = currentUserTurn;
    }
  });

  if (latestTodoTurn != null) {
    todosByUserTurn.set(latestTodoTurn, latestTodos);
  }
  return todosByUserTurn;
}

function parseTodos(value: unknown): Todo[] | null {
  if (!Array.isArray(value)) return null;
  const todos: Todo[] = [];
  for (const item of value) {
    if (
      item == null ||
      typeof item !== "object" ||
      typeof (item as { content?: unknown }).content !== "string"
    ) {
      return null;
    }
    const status = (item as { status?: unknown }).status;
    if (
      status !== "pending" &&
      status !== "in_progress" &&
      status !== "completed"
    ) {
      return null;
    }
    todos.push({
      content: (item as { content: string }).content,
      status,
    });
  }
  return todos;
}

function runDurationMs(run: Run): number | null {
  const startedAt = Date.parse(run.startedAt ?? "");
  const updatedAt = Date.parse(run.updatedAt);
  if (!Number.isFinite(startedAt) || !Number.isFinite(updatedAt)) return null;
  return Math.max(0, updatedAt - startedAt);
}

type TurnRunMetadata = {
  promptedAt: string;
  durationMs?: number;
};

function mapRunMetadataToUserTurns(
  messages: readonly BaseMessage[],
  runs: readonly Run[],
): Map<string, TurnRunMetadata> {
  const userTurns = messages.flatMap((message, index) =>
    isHumanMessage(message) && !isHostNotice(message)
      ? [{ message, key: userTurnKey(message, index) }]
      : [],
  );
  const byMessageId = new Map(
    userTurns.flatMap(({ message, key }) =>
      message.id != null ? [[String(message.id), key] as const] : [],
    ),
  );
  const metadata = new Map<string, TurnRunMetadata>();
  const accumulated = new Map<string, number>();
  const assignedTurns = new Set<string>();
  let fallbackIndex = 0;
  let currentTurn: string | null = null;

  const chronological = [...runs].sort((left, right) => {
    const leftAt = Date.parse(left.startedAt ?? left.createdAt);
    const rightAt = Date.parse(right.startedAt ?? right.createdAt);
    return leftAt - rightAt;
  });

  for (const run of chronological) {
    if (run.kind === "prompt") {
      const exact =
        run.inputMessageId != null
          ? byMessageId.get(run.inputMessageId)
          : undefined;
      while (
        exact == null &&
        userTurns[fallbackIndex] != null &&
        assignedTurns.has(userTurns[fallbackIndex].key)
      ) {
        fallbackIndex += 1;
      }
      currentTurn = exact ?? userTurns[fallbackIndex]?.key ?? null;
      if (currentTurn != null) {
        assignedTurns.add(currentTurn);
        accumulated.set(currentTurn, 0);
        metadata.set(currentTurn, { promptedAt: run.createdAt });
        if (exact == null) fallbackIndex += 1;
      }
    } else if (run.kind === "regenerate" && currentTurn != null) {
      accumulated.set(currentTurn, 0);
    } else if (run.kind !== "resume") {
      continue;
    }

    if (currentTurn == null) continue;
    const duration = runDurationMs(run);
    if (duration != null) {
      accumulated.set(
        currentTurn,
        (accumulated.get(currentTurn) ?? 0) + duration,
      );
    }
    if (run.status === "pending" || run.status === "running") {
      const current = metadata.get(currentTurn);
      if (current) metadata.set(currentTurn, { promptedAt: current.promptedAt });
    } else if (run.status === "interrupted") {
      const current = metadata.get(currentTurn);
      if (current) metadata.set(currentTurn, { promptedAt: current.promptedAt });
    } else {
      const current = metadata.get(currentTurn);
      if (current) {
        metadata.set(currentTurn, {
          ...current,
          durationMs: accumulated.get(currentTurn) ?? 0,
        });
      }
    }
  }
  return metadata;
}

function formatDuration(durationMs: number): string {
  const seconds = durationMs / 1000;
  if (seconds < 1) return `${Math.max(0.1, seconds).toFixed(1)} s`;
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  if (minutes < 60) return `${minutes} min ${remainingSeconds} s`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${minutes % 60} min`;
}

function formatPromptTimestamp(value: string): string | null {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return null;
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

const TurnMetadata = ({
  promptedAt,
  durationMs,
}: {
  promptedAt?: string;
  durationMs?: number;
}) => {
  const promptLabel = promptedAt ? formatPromptTimestamp(promptedAt) : null;
  const durationLabel =
    durationMs != null ? formatDuration(durationMs) : null;
  if (!promptLabel && !durationLabel) return null;
  const title = [
    promptLabel ? `Prompt sent: ${promptLabel}` : null,
    durationLabel ? `Response time: ${durationLabel}` : null,
  ]
    .filter(Boolean)
    .join(". ");
  return (
    <div
      className="ml-auto flex items-center gap-1 pr-0.5 font-mono text-[10px] leading-none tabular-nums text-meta dark:text-panel-dim"
      title={title}
      aria-label={title}
    >
      {promptLabel && (
        <time dateTime={promptedAt} suppressHydrationWarning>
          {promptLabel}
        </time>
      )}
      {promptLabel && durationLabel && <span aria-hidden="true">/</span>}
      {durationLabel && (
        <>
          <Clock3Icon aria-hidden="true" className="size-2.5" />
          <span>{durationLabel}</span>
        </>
      )}
    </div>
  );
};

const UserTurn = ({
  message,
  anchorId,
  sending,
  todos,
  durationMs,
  promptedAt,
  error,
}: {
  message: BaseMessage;
  anchorId: string;
  sending: boolean;
  todos?: Todo[];
  durationMs?: number;
  promptedAt?: string;
  error?: string;
}) => {
  const displayText = message.additional_kwargs?.display_text;
  const { text, context, source } = presentSideChannelMessage(
    typeof displayText === "string" ? displayText : message.text,
  );
  const inline = getFileAttachments(message);
  const hasInlineImages = inline.some(
    (attachment) => getMediaCategory(attachment) === "image",
  );
  const files = useAttachedFiles(getAttachmentIds(message))
    .filter((file) => !(hasInlineImages && file.mime_type.startsWith("image/")))
    .map((file): AttachmentData => ({
      id: file.id,
      type: "file",
      url: contentUrl(file),
      filename: file.filename,
      mediaType: file.mime_type,
    }));
  const persistedFiles = new Set(
    files.map((file) => `${file.filename ?? ""}\0${file.mediaType}`),
  );
  const attachments = [
    ...inline.filter(
      (file) =>
        getMediaCategory(file) === "image" ||
        !persistedFiles.has(`${file.filename ?? ""}\0${file.mediaType}`),
    ),
    ...files,
  ];
  return (
    <div id={anchorId} className="flex flex-col gap-2">
      {attachments.length > 0 && (
        <div className="flex items-center justify-end gap-2">
          {sending && !text && (
            <Loader
              size={14}
              className="shrink-0 text-meta motion-reduce:animate-none dark:text-panel-dim"
              aria-hidden="true"
            />
          )}
          <Attachments variant="inline">
            {attachments.map((attachment) => {
              const label = getAttachmentLabel(attachment);
              return (
                <AttachmentHoverCard key={attachment.id}>
                  <AttachmentHoverCardTrigger asChild>
                    <Attachment data={attachment}>
                      <div className="relative size-5 shrink-0">
                        <div className="absolute inset-0 flex items-center justify-center transition-opacity group-hover:opacity-0">
                          <AttachmentPreview
                            fallbackIcon={
                              <FileIcon
                                mimeType={attachment.mediaType}
                                className="h-5 w-4"
                              />
                            }
                          />
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
                      {attachment.type === "file" && attachment.url && (
                        <a
                          className="inline-flex items-center gap-1.5 whitespace-nowrap text-sm font-medium text-petrol hover:underline"
                          download={attachment.filename}
                          href={attachment.url}
                        >
                          <DownloadIcon className="size-3.5" />
                          Download
                        </a>
                      )}
                    </div>
                  </AttachmentHoverCardContent>
                </AttachmentHoverCard>
              );
            })}
          </Attachments>
        </div>
      )}
      {context.length > 0 && (
        <SideChannelContextDetails messages={context} source={source} />
      )}
      {text && (
        <Message from="user">
          <div
            className={
              sending
                ? "ml-auto flex max-w-[82%] items-end justify-end gap-2"
                : "contents"
            }
          >
            {sending && (
              <Loader
                size={14}
                className="shrink-0 text-meta motion-reduce:animate-none dark:text-panel-dim"
                aria-hidden="true"
              />
            )}
            <MessageContent
              className={
                sending
                  ? "group-[.is-user]:ml-0 group-[.is-user]:max-w-full"
                  : undefined
              }
            >
              <MessageResponse>{text}</MessageResponse>
            </MessageContent>
          </div>
        </Message>
      )}
      <TurnMetadata promptedAt={promptedAt} durationMs={durationMs} />
      {todos && todos.length > 0 && (
        <TodoList
          todos={todos}
          className="ml-auto w-full max-w-[82%] rounded-lg border border-border/50 bg-muted/30 p-4"
        />
      )}
      {error != null && (
        <Error>
          <ErrorContent>An error occurred.</ErrorContent>
          <ErrorDetails>
            <div>{error}</div>
          </ErrorDetails>
        </Error>
      )}
    </div>
  );
};

const OptimisticUserTurn = ({ prompt }: { prompt: QueuedPrompt }) => {
  return (
    <div
      className="flex flex-col gap-2"
      role="status"
      aria-label="Sending queued message"
    >
      {prompt.attachments.length > 0 && (
        <div className="flex items-center justify-end gap-2">
          {!prompt.text && (
            <Loader
              size={14}
              className="shrink-0 text-meta motion-reduce:animate-none dark:text-panel-dim"
              aria-hidden="true"
            />
          )}
          <div className="flex flex-wrap justify-end gap-1.5">
            {prompt.attachments.map((attachment, index) => (
              <span
                key={`${attachment.filename}-${index}`}
                className="inline-flex max-w-52 items-center gap-1.5 rounded-md border border-border/70 bg-card px-2 py-1 text-[10.5px] font-medium text-body dark:bg-panel dark:text-panel-body"
              >
                <PaperclipIcon className="size-3 shrink-0 text-meta" />
                <span className="truncate">{attachment.filename}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      {prompt.text && (
        <Message from="user">
          <div className="ml-auto flex max-w-[82%] items-end justify-end gap-2">
            <Loader
              size={14}
              className="shrink-0 text-meta motion-reduce:animate-none dark:text-panel-dim"
              aria-hidden="true"
            />
            <MessageContent className="group-[.is-user]:ml-0 group-[.is-user]:max-w-full">
              <MessageResponse>{prompt.text}</MessageResponse>
            </MessageContent>
          </div>
        </Message>
      )}
    </div>
  );
};

const SideChannelContextDetails = ({
  messages,
  source,
}: {
  messages: SideChannelContextMessage[];
  source: string | null;
}) => (
  <div className="flex justify-end">
    <Collapsible className="group/side-channel-context flex w-fit max-w-[78%] flex-col items-end">
      <CollapsibleTrigger className="ml-auto flex cursor-pointer items-center gap-2 rounded-lg border border-border/70 bg-card px-2.5 py-1.5 text-left text-[11.5px] text-meta shadow-[0_1px_2px_rgba(0,0,0,0.03)] transition-colors hover:border-border-hover hover:text-foreground dark:bg-panel">
        {source === "slack" ? (
          <SlackLogo className="size-4 rounded-[4px] border-0 shadow-none" />
        ) : source === "telegram" ? (
          <TelegramLogo className="size-4" />
        ) : source === "whatsapp" ? (
          <WhatsAppLogo className="size-4" />
        ) : (
          <MessagesSquareIcon className="size-3.5 text-petrol dark:text-panel-terminal" />
        )}
        <span className="font-semibold text-body dark:text-panel-body">
          {source === "slack"
            ? "Slack"
            : source === "telegram"
              ? "Telegram"
              : source === "whatsapp"
                ? "WhatsApp"
              : (source ?? "Side channel")}
        </span>
        <span className="font-mono text-[10px]">context</span>
        <span className="font-mono text-[10.5px]">
          {messages.length} message{messages.length === 1 ? "" : "s"}
        </span>
        <ChevronDownIcon className="size-3 shrink-0 -rotate-90 transition-transform duration-200 group-data-[state=open]/side-channel-context:rotate-0" />
      </CollapsibleTrigger>
      <CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down w-fit max-w-full overflow-hidden">
        <div className="mt-2 flex max-h-80 max-w-[min(34rem,72vw)] flex-col items-end gap-2.5 overflow-y-auto">
          {messages.map((message, index) => (
            <div
              key={`${message.participantId}-${index}`}
              className="w-fit max-w-full rounded-[12px_12px_3px_12px] border border-border/60 bg-white px-3 py-1.5 shadow-[0_1px_2px_rgba(0,0,0,0.035)] dark:bg-panel"
            >
              <div className="mb-0.5 font-mono text-[9.5px] leading-none text-meta dark:text-panel-dim">
                {message.participantId}
              </div>
              <div className="whitespace-pre-wrap text-[12.5px] leading-[1.4] text-body dark:text-panel-body">
                {message.text}
              </div>
            </div>
          ))}
        </div>
      </CollapsibleContent>
    </Collapsible>
  </div>
);

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
  respond: (
    response: HitlResponse,
    interruptId: string | null,
  ) => Promise<void>;
  /** A run is executing: a card's approval waits for it to settle. */
  resumeInFlight: boolean;
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
  resumeInFlight,
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
  // A subagent of this chain paused on an approval: its card shows the
  // approval, the chain stays open and stops reading as active.
  const pausedSubagents = chainSubagents.filter(
    (s) =>
      s.status === "running" &&
      nestedInterrupts.some((i) => claimsInterrupt(i, s)),
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
            (r) =>
              !r.sub && r.state === "awaiting-approval" && !decisions[r.tc.id],
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
              resumeInFlight={resumeInFlight}
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
      {tools.map(({ tc }) => (
        <ArtifactCards key={`files-${tc.id}`} toolCallId={tc.callId ?? tc.id} />
      ))}
      {tools.map(({ tc, sub }) => {
        const app = sub ? null : getMcpAppInfo(tc);
        if (!app) return null;
        const { serverName, toolName, icon } = describe(tc.name);
        return (
          <AppSlot
            key={`app-${tc.id}`}
            toolCallId={tc.callId ?? tc.id}
            app={{
              input: tc.args,
              output: tc.output,
              structuredContent: getStructuredContent(tc),
              errorText: tc.error,
              toolName,
              appToolInfo: app,
              serverName,
              serverIcon: icon,
            }}
          />
        );
      })}
    </div>
  );
};

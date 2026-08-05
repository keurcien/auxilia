"use client";

import { cn } from "@/lib/utils";
import { Loader2, XCircleIcon } from "lucide-react";
import { memo, useEffect, useRef, useState } from "react";
import { Loader } from "@/components/ai-elements/loader";
import {
	ChainRail,
	ChainReasoningLine,
	ChainStep,
	ChainStepIcon,
	StepCode,
	StepSection,
	humanizeToolName,
	summarizeToolArgs,
} from "@/components/ai-elements/chain-of-thought";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import { extractToolErrorText } from "@/lib/utils/tool-content";
import type { SubagentStreamInterface } from "@langchain/langgraph-sdk/ui";

// ---------------------------------------------------------------------------
// Petrol Mono (design 8a): a subagent call is a chain-of-thought step —
// node = the agent's emoji on its pastel tile, title = "Ask {Agent}",
// expanded = TASK block → the subagent's own nested rail (tool calls +
// ✦ italic reasoning lines, one nesting level max) → RESULT block.
// ---------------------------------------------------------------------------

const formatElapsed = (ms: number) => {
	if (ms < 1000) return `${Math.round(ms)}ms`;
	const s = Math.round(ms / 1000);
	if (s < 60) return `${s}s`;
	return `${Math.floor(s / 60)}m ${s % 60}s`;
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getTextFromMessage(msg: any): string {
	if (typeof msg.content === "string") return msg.content;
	if (Array.isArray(msg.content)) {
		return (
			msg.content
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				.filter((c: any) => c.type === "text")
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				.map((c: any) => c.text)
				.join("")
		);
	}
	return "";
}

/**
 * Parse a tool name into server + tool parts.
 * Same fallback logic as the supervisor chat page.
 */
function parseToolName(name: string): { serverName: string; toolName: string } {
	const sep = name.indexOf("_");
	if (sep === -1) return { serverName: name, toolName: name };
	return { serverName: name.slice(0, sep), toolName: name.slice(sep + 1) };
}

/**
 * Extract plain text/JSON output from a tool message content.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getToolOutputContent(msg: any): unknown {
	if (!msg) return undefined;
	const content = msg.content;
	if (typeof content === "string") {
		try {
			return JSON.parse(content);
		} catch {
			return content;
		}
	}
	return content;
}

interface MCPServerInfo {
	name: string;
	iconUrl?: string | null;
}

/**
 * The subagent's internal conversation as a nested rail: ✦ italic reasoning
 * lines for AI text, nested chain steps for its tool calls.
 */
const SubAgentConversation = memo(
	({
		messages,
		isStreaming,
		mcpServers,
	}: {
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		messages: any[];
		isStreaming: boolean;
		mcpServers?: MCPServerInfo[];
	}) => {
		if (!messages || messages.length === 0) return null;

		// Build a map of tool_call_id → tool message for result lookup
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		const toolResults = new Map<string, any>();
		for (const msg of messages) {
			if (msg.type === "tool") {
				const tcId = msg.tool_call_id ?? msg.toolCallId;
				if (tcId) toolResults.set(tcId, msg);
			}
		}

		const knownNames = (mcpServers ?? [])
			.map((s) => s.name)
			.sort((a, b) => b.length - a.length);

		const elements: React.ReactNode[] = [];

		for (let i = 0; i < messages.length; i++) {
			const msg = messages[i];
			if (msg.type !== "ai" && msg.type !== "assistant") continue;

			const text = getTextFromMessage(msg);
			const toolCalls = msg.tool_calls ?? msg.toolCalls ?? [];
			const isLast = i === messages.length - 1;

			if (text) {
				elements.push(
					<ChainReasoningLine key={`ai-${msg.id ?? i}`}>
						{text}
						{isStreaming && isLast && toolCalls.length === 0 && (
							<span className="ml-0.5 inline-block h-3 w-1 animate-pulse rounded-sm bg-petrol align-text-bottom" />
						)}
					</ChainReasoningLine>,
				);
			}

			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			toolCalls.forEach((tc: any, j: number) => {
				const tcId = tc.id ?? `${msg.id}-tc-${j}`;
				const toolMsg = toolResults.get(tcId);
				const isError = toolMsg?.status === "error";
				const isDone = !!toolMsg;
				const fullName = (tc.name ?? "tool") as string;
				const { serverName, toolName } = (() => {
					for (const sn of knownNames) {
						if (fullName === sn || fullName.startsWith(`${sn}_`)) {
							const suffix = fullName.slice(sn.length);
							return {
								serverName: sn,
								toolName: suffix.startsWith("_")
									? suffix.slice(1)
									: suffix || fullName,
							};
						}
					}
					return parseToolName(fullName);
				})();
				const serverIcon =
					mcpServers?.find((s) => s.name === serverName)?.iconUrl ?? undefined;
				const output = getToolOutputContent(toolMsg);
				const errorText =
					isError && toolMsg ? extractToolErrorText(toolMsg.content) : undefined;

				elements.push(
					<ChainStep
						key={tcId}
						nested
						node={<ChainStepIcon icon={serverIcon} name={serverName} />}
						title={humanizeToolName(toolName)}
						summary={summarizeToolArgs(tc.args)}
						meta={
							!isDone ? (
								<Loader2 className="size-3 animate-spin text-petrol" />
							) : isError ? (
								<XCircleIcon className="size-3.5 text-destructive" />
							) : undefined
						}
					>
						{tc.args !== undefined && (
							<StepSection label="PARAMETERS">
								<StepCode value={tc.args} />
							</StepSection>
						)}
						{errorText !== undefined ? (
							<StepSection label="ERROR" error>
								<StepCode value={errorText} />
							</StepSection>
						) : (
							output !== undefined && (
								<StepSection label="RESULT">
									<StepCode value={output} />
								</StepSection>
							)
						)}
					</ChainStep>,
				);
			});
		}

		if (elements.length === 0) return null;

		return <ChainRail>{elements}</ChainRail>;
	},
);
SubAgentConversation.displayName = "SubAgentConversation";

// ---------------------------------------------------------------------------
// SubAgentCard: a subagent call rendered as a chain-of-thought step
// ---------------------------------------------------------------------------

interface SubAgentCardProps {
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	subagent: SubagentStreamInterface<any, any, any>;
	mcpServers?: MCPServerInfo[];
	/** The workspace agent behind this subagent, for its emoji/pastel tile. */
	agent?: { name: string; emoji?: string | null; color?: string | null };
	onOpen?: () => void;
	// Internal conversation restored from the subgraph checkpoint on refresh.
	// The SDK can't inject these into the (reconstructed) subagent via the custom
	// transport, so the page fetches them on demand and passes them here.
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	fallbackMessages?: any[];
}

export const SubAgentCard = memo(
	({ subagent, mcpServers, agent, onOpen, fallbackMessages }: SubAgentCardProps) => {
		const {
			status,
			toolCall,
			result,
			startedAt,
			completedAt,
			messages,
			values,
		} = subagent;
		const isStreaming = status === "running";
		const isError = status === "error";
		const description = toolCall?.args?.description as string | undefined;
		const subagentType = toolCall?.args?.subagent_type as string | undefined;
		const agentLabel =
			agent?.name ?? subagentType?.replaceAll("_", " ") ?? "subagent";
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		const todos = ((values as any)?.todos ?? []) as Todo[];

		const elapsed =
			startedAt && completedAt
				? completedAt.getTime() - startedAt.getTime()
				: undefined;

		// Streaming and errored steps start open; opening fetches restored
		// history (onOpen) when the live messages are empty.
		const [autoOpen, setAutoOpen] = useState(isStreaming || isError);
		const requestedInitialHistory = useRef(false);

		// Reopen when a new streaming phase starts — state is adjusted during
		// render (not in an effect) per react-hooks/set-state-in-effect.
		const [wasStreaming, setWasStreaming] = useState(isStreaming);
		if (isStreaming !== wasStreaming) {
			setWasStreaming(isStreaming);
			if (isStreaming) setAutoOpen(true);
		}

		useEffect(() => {
			if (isError && onOpen && !requestedInitialHistory.current) {
				requestedInitialHistory.current = true;
				onOpen();
			}
		}, [isError, onOpen]);

		const convoMessages =
			messages && messages.length > 0 ? messages : (fallbackMessages ?? []);
		const hasConversation = convoMessages.length > 0;

		return (
			<ChainStep
				node={
					<AgentAvatar
						color={agent?.color}
						emoji={agent?.emoji}
						size="2xs"
						shape="tile"
						className="relative z-[1]"
					/>
				}
				title={`Ask ${agentLabel}`}
				summary={description}
				lockOpen={autoOpen}
				onOpenChange={(open) => {
					setAutoOpen(false);
					if (open) onOpen?.();
				}}
				meta={
					isStreaming || status === "pending" ? (
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
				{description && (
					<StepSection label="TASK">
						<StepCode value={description} />
					</StepSection>
				)}
				{todos.length > 0 && <TodoList todos={todos} />}
				{hasConversation && (
					<SubAgentConversation
						messages={convoMessages}
						isStreaming={isStreaming}
						mcpServers={mcpServers}
					/>
				)}
				{result != null && result !== "" && (
					<StepSection label="RESULT">
						<div className="min-w-0 whitespace-pre-wrap rounded-[6px] border border-border bg-card px-3 py-2.5 text-[12.5px] leading-[1.6] text-body dark:text-panel-body">
							{String(result)}
						</div>
					</StepSection>
				)}
				{isError && subagent.error != null && (
					<StepSection label="ERROR" error>
						<StepCode
							value={
								subagent.error instanceof Error
									? subagent.error.message
									: String(subagent.error)
							}
						/>
					</StepSection>
				)}
			</ChainStep>
		);
	},
);

SubAgentCard.displayName = "SubAgentCard";

// ---------------------------------------------------------------------------
// SubAgentProgress: aggregate progress bar for multiple subagents
// ---------------------------------------------------------------------------

interface SubAgentProgressProps {
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	subagents: SubagentStreamInterface<any, any, any>[];
}

export const SubAgentProgress = memo(({ subagents }: SubAgentProgressProps) => {
	const completed = subagents.filter(
		(s) => s.status === "complete" || s.status === "error",
	).length;
	const total = subagents.length;

	if (total <= 1) return null;

	const pct = (completed / total) * 100;

	return (
		<div className="flex items-center gap-2 font-mono text-[10.5px] text-meta dark:text-panel-dim">
			<div className="h-1 flex-1 overflow-hidden rounded-full bg-hover dark:bg-white/10">
				<div
					className="h-full rounded-full bg-petrol transition-all duration-300"
					style={{ width: `${pct}%` }}
				/>
			</div>
			<span>
				{completed}/{total} complete
			</span>
		</div>
	);
});

SubAgentProgress.displayName = "SubAgentProgress";

// ---------------------------------------------------------------------------
// SynthesisIndicator: shown while supervisor synthesizes after subagents
// ---------------------------------------------------------------------------

interface SynthesisIndicatorProps {
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	subagents: SubagentStreamInterface<any, any, any>[];
	isCoordinatorStreaming: boolean;
}

export const SynthesisIndicator = memo(
	({ subagents, isCoordinatorStreaming }: SynthesisIndicatorProps) => {
		const allDone =
			subagents.length > 0 &&
			subagents.every(
				(s) => s.status === "complete" || s.status === "error",
			);

		if (!allDone || !isCoordinatorStreaming) return null;

		return (
			<div className={cn("flex animate-pulse items-center gap-2 text-[12.5px] italic text-muted-foreground")}>
				<Loader size={12} className="animate-spin" />
				Synthesizing results…
			</div>
		);
	},
);

SynthesisIndicator.displayName = "SynthesisIndicator";

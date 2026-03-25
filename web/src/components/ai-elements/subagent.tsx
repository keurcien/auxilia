"use client";

import { useControllableState } from "@radix-ui/react-use-controllable-state";
import {
	Collapsible,
	CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "lucide-react";
import { memo, useEffect } from "react";
import { Loader } from "@/components/ai-elements/loader";
import {
	Tool,
	ToolContent,
	ToolContentInner,
	ToolHeader,
	ToolInput,
	ToolOutput,
} from "@/components/ai-elements/tool";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import type { SubagentStreamInterface } from "@langchain/langgraph-sdk/ui";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type Status = "pending" | "running" | "complete" | "error";

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
		return msg.content
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			.filter((c: any) => c.type === "text")
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			.map((c: any) => c.text)
			.join("");
	}
	return "";
}

/**
 * Parse a tool name into server + tool parts.
 * Same fallback logic as the coordinator chat page.
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

type ToolRenderState =
	| "output-available"
	| "output-error"
	| "input-available";

/**
 * Renders the subagent's conversation as a mini log:
 * AI text paragraphs + Tool cards (same as coordinator).
 */
interface MCPServerInfo {
	name: string;
	iconUrl?: string | null;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const SubAgentConversation = memo(({ messages, isStreaming, mcpServers }: { messages: any[]; isStreaming: boolean; mcpServers?: MCPServerInfo[] }) => {
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

	const elements: React.ReactNode[] = [];

	for (let i = 0; i < messages.length; i++) {
		const msg = messages[i];

		if (msg.type === "ai" || msg.type === "assistant") {
			const text = getTextFromMessage(msg);
			const toolCalls = msg.tool_calls ?? msg.toolCalls ?? [];
			const isLast = i === messages.length - 1;

			if (text) {
				elements.push(
					<p key={`ai-${msg.id ?? i}`} className="text-sm whitespace-pre-wrap">
						{text}
						{isStreaming && isLast && toolCalls.length === 0 && (
							<span className="inline-block h-3.5 w-1 ml-0.5 animate-pulse bg-primary rounded-sm align-text-bottom" />
						)}
					</p>,
				);
			}

			// Render tool calls with the same Tool components as the coordinator
			{/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
			toolCalls.forEach((tc: any, j: number) => {
				const tcId = tc.id ?? `${msg.id}-tc-${j}`;
				const toolMsg = toolResults.get(tcId);
				const isError = toolMsg?.status === "error";
				const isDone = !!toolMsg;
				const toolState: ToolRenderState = isDone
					? isError
						? "output-error"
						: "output-available"
					: "input-available";
				const knownNames = (mcpServers ?? []).map((s) => s.name).sort((a, b) => b.length - a.length);
				const { serverName, toolName } = knownNames.length > 0
					? (() => {
						const fullName = tc.name ?? "tool";
						for (const sn of knownNames) {
							if (fullName === sn || fullName.startsWith(`${sn}_`)) {
								const suffix = fullName.slice(sn.length);
								return { serverName: sn, toolName: suffix.startsWith("_") ? suffix.slice(1) : suffix || fullName };
							}
						}
						return parseToolName(fullName);
					})()
					: parseToolName(tc.name ?? "tool");
				const serverIcon = mcpServers?.find((s) => s.name === serverName)?.iconUrl ?? undefined;
				const output = getToolOutputContent(toolMsg);

				elements.push(
					<Tool key={tcId} toolState={toolState}>
						<ToolHeader
							title={toolName}
							type={`tool-${tc.name}`}
							state={toolState}
							mcpServerName={serverName}
							mcpServerIcon={serverIcon}
						/>
						<ToolContent>
							<ToolContentInner>
								{tc.args !== undefined && (
									<ToolInput input={tc.args} />
								)}
								{(output !== undefined || isError || !isDone) && (
									<ToolOutput
										output={output as React.ReactNode}
										errorText={
											isError && toolMsg
												? typeof toolMsg.content === "string"
													? toolMsg.content
													: "Tool execution failed"
												: undefined
										}
									/>
								)}
							</ToolContentInner>
						</ToolContent>
					</Tool>,
				);
			});
		}
	}

	if (elements.length === 0) return null;

	return <div className="space-y-2">{elements}</div>;
});
SubAgentConversation.displayName = "SubAgentConversation";

// ---------------------------------------------------------------------------
// StatusIcon + StatusBadge
// ---------------------------------------------------------------------------

const StatusIcon = memo(({ status }: { status: Status }) => {
	switch (status) {
		case "pending":
			return (
				<span className="text-muted-foreground text-sm">&#9675;</span>
			);
		case "running":
			return <Loader size={16} className="animate-spin text-primary" />;
		case "complete":
			return <span className="text-emerald-500 text-sm">&#10003;</span>;
		case "error":
			return <span className="text-red-500 text-sm">&#10005;</span>;
	}
});
StatusIcon.displayName = "StatusIcon";

const statusBadgeStyles: Record<Status, string> = {
	pending: "bg-muted text-muted-foreground",
	running: "bg-primary/10 text-primary",
	complete: "bg-emerald-500/10 text-emerald-600",
	error: "bg-red-500/10 text-red-600",
};

const StatusBadge = memo(({ status }: { status: Status }) => (
	<span
		className={cn(
			"rounded-full px-2 py-0.5 text-[10px] font-medium capitalize",
			statusBadgeStyles[status],
		)}
	>
		{status === "complete" ? "finished" : status}
	</span>
));
StatusBadge.displayName = "StatusBadge";

// ---------------------------------------------------------------------------
// SubAgentCard: renders a SubagentStreamInterface from the SDK
// ---------------------------------------------------------------------------

interface SubAgentCardProps {
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	subagent: SubagentStreamInterface<any, any, any>;
	mcpServers?: MCPServerInfo[];
}

export const SubAgentCard = memo(({ subagent, mcpServers }: SubAgentCardProps) => {
	const { status, toolCall, result, startedAt, completedAt, messages, values } =
		subagent;
	const isStreaming = status === "running";
	const isError = status === "error";
	const description = toolCall?.args?.description as string | undefined;
	const subagentType = toolCall?.args?.subagent_type as string | undefined;
	const title = subagentType?.replaceAll("_", " ") ?? "Sub-agent";
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const todos = ((values as any)?.todos ?? []) as Todo[];

	const elapsed =
		startedAt && completedAt
			? completedAt.getTime() - startedAt.getTime()
			: undefined;

	const [isOpen, setIsOpen] = useControllableState({
		defaultProp: isStreaming || isError,
	});

	useEffect(() => {
		if (isStreaming) setIsOpen(true);
	}, [isStreaming, setIsOpen]);

	const hasConversation = messages && messages.length > 0;
	const hasBody =
		description || todos.length > 0 || hasConversation || result || isError;

	return (
		<Collapsible
			className="not-prose w-full rounded-lg border border-border bg-card shadow-sm overflow-hidden"
			open={isOpen}
			onOpenChange={setIsOpen}
		>
			{/* ---- Header ---- */}
			<CollapsibleTrigger className="flex w-full items-center justify-between gap-3 p-3 text-sm transition-colors hover:bg-muted/50 cursor-pointer">
				<div className="flex items-center gap-2.5 min-w-0">
					<StatusIcon status={status} />
					<span className="font-medium truncate">{title}</span>
					{description && (
						<span className="hidden sm:inline text-xs text-muted-foreground truncate max-w-[200px]">
							{description}
						</span>
					)}
				</div>
				<div className="flex items-center gap-2 shrink-0">
					{elapsed != null && (
						<span className="text-xs text-muted-foreground">
							{formatElapsed(elapsed)}
						</span>
					)}
					<StatusBadge status={status} />
					<ChevronDownIcon
						className={cn(
							"size-4 text-muted-foreground transition-transform",
							isOpen ? "rotate-0" : "-rotate-90",
						)}
					/>
				</div>
			</CollapsibleTrigger>

			{/* ---- Collapsible body ---- */}
			{hasBody && (
				<div
					className={cn(
						"grid transition-[grid-template-rows] duration-300 ease-out",
						isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
					)}
				>
					<div className="overflow-hidden">
						<div className="border-t border-border px-4 py-3 space-y-3">
							{description && (
								<p className="text-xs text-muted-foreground">
									{description}
								</p>
							)}
							{todos.length > 0 && <TodoList todos={todos} />}
							{hasConversation && (
								<SubAgentConversation
									messages={messages}
									isStreaming={isStreaming}
									mcpServers={mcpServers}
								/>
							)}
							{result && !hasConversation && (
								<div className="text-sm whitespace-pre-wrap line-clamp-6">
									{result}
								</div>
							)}
							{isError && subagent.error != null && (
								<div className="text-sm text-red-500">
									{subagent.error instanceof Error
										? subagent.error.message
										: String(subagent.error)}
								</div>
							)}
						</div>
					</div>
				</div>
			)}
		</Collapsible>
	);
});

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
		<div className="flex items-center gap-2 text-xs text-muted-foreground">
			<div className="h-1.5 flex-1 rounded-full bg-muted overflow-hidden">
				<div
					className="h-full rounded-full bg-primary transition-all duration-300"
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
// SynthesisIndicator: shown while coordinator synthesizes after subagents
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
			<div className="flex items-center gap-2 text-xs text-muted-foreground animate-pulse">
				<Loader size={12} className="animate-spin" />
				Synthesizing results...
			</div>
		);
	},
);

SynthesisIndicator.displayName = "SynthesisIndicator";

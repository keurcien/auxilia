"use client";

import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDownIcon, Loader2 } from "lucide-react";
import Image from "next/image";
import type { ReactNode } from "react";
import { useState } from "react";
import { CodeBlock, SHIKI_MAX_CHARS } from "./code-block";
import { MessageResponse } from "./message";
import { Shimmer } from "./shimmer";

// ---------------------------------------------------------------------------
// Petrol Mono chain of thought (design 8a): the agent's work renders as a
// mid-air timeline — a collapsible "✦ Worked" header, then steps hanging on
// a 1px rail. Tool calls and subagent calls are both steps.
// ---------------------------------------------------------------------------

/** Built-in code-execution (sandbox) tools — not MCP tools, so server-name
 * matching can't resolve an icon for them. They carry the terminal icon. */
export const TERMINAL_ICON =
	"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/terminal.png";

const SANDBOX_TOOL_NAMES = new Set([
	"ls",
	"read_file",
	"write_file",
	"edit_file",
	"glob",
	"grep",
	"execute",
	// Sandbox lifecycle tools (backend/app/sandbox/tools.py)
	"create_sandbox",
	"connect_sandbox",
]);

export function isSandboxTool(name: string): boolean {
	return SANDBOX_TOOL_NAMES.has(name);
}

/** "run_query" / "searchMessages" → "Run query" / "Search messages" */
export function humanizeToolName(name: string): string {
	const spaced = name
		.replace(/([a-z0-9])([A-Z])/g, "$1 $2")
		.replace(/[_-]+/g, " ")
		.trim()
		.toLowerCase();
	return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

const SUMMARY_ARG_PRIORITY = [
	"description",
	"query",
	"sql",
	"q",
	"prompt",
	"text",
	"message",
	"title",
	"name",
	"command",
	"path",
	"url",
	"channel",
];

const truncate = (value: string, max = 90) => {
	const oneLine = value.replace(/\s+/g, " ").trim();
	return oneLine.length > max ? `${oneLine.slice(0, max)}…` : oneLine;
};

/** Best-effort plain-language summary of a tool call's arguments. */
export function summarizeToolArgs(args: unknown): string {
	if (!args || typeof args !== "object") return "";
	const entries = new Map(Object.entries(args as Record<string, unknown>));
	for (const key of SUMMARY_ARG_PRIORITY) {
		const value = entries.get(key);
		if (typeof value === "string" && value.trim()) return truncate(value);
	}
	for (const value of entries.values()) {
		if (typeof value === "string" && value.trim()) return truncate(value);
	}
	return "";
}

// ---------------------------------------------------------------------------
// ChainOfThought — collapsible container with the rail
// ---------------------------------------------------------------------------

export type ChainOfThoughtProps = {
	/** A step is still running — the chain stays open while active. */
	active?: boolean;
	/** Force open (e.g. an undecided approval). */
	lockOpen?: boolean;
	toolCount?: number;
	subagentCount?: number;
	className?: string;
	children: ReactNode;
};

export const ChainOfThought = ({
	active = false,
	lockOpen = false,
	toolCount = 0,
	subagentCount = 0,
	className,
	children,
}: ChainOfThoughtProps) => {
	const [userOpenPreference, setUserOpenPreference] = useState<boolean | null>(
		null,
	);
	// Open by default and stays open when the run finishes — collapsing is
	// the user's call (except an undecided approval, which forces open).
	const isOpen = lockOpen ? true : (userOpenPreference ?? true);

	const counts = [
		toolCount > 0 &&
			`${toolCount} tool call${toolCount === 1 ? "" : "s"}`,
		subagentCount > 0 &&
			`${subagentCount} subagent${subagentCount === 1 ? "" : "s"}`,
	]
		.filter(Boolean)
		.join(" · ");

	return (
		<Collapsible
			open={isOpen}
			onOpenChange={setUserOpenPreference}
			className={cn("not-prose group/cot w-full min-w-0", className)}
		>
			<CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-2.5 py-0.5 text-left">
				{active ? (
					<DotsLabel className="text-[13px] font-semibold text-body dark:text-panel-body">
						Working
					</DotsLabel>
				) : (
					<span className="text-[13px] font-semibold text-body dark:text-panel-body">
						Worked
					</span>
				)}
				{counts && (
					<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
						{counts}
					</span>
				)}
				<ChevronDownIcon className="size-3 shrink-0 text-meta transition-transform duration-200 -rotate-90 group-data-[state=open]/cot:rotate-0" />
			</CollapsibleTrigger>
			<CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
				<ChainRail className="pt-1.5">{children}</ChainRail>
			</CollapsibleContent>
		</Collapsible>
	);
};

/** A word followed by three dots pulsing in sequence — the header's
 *  in-progress state. */
const DotsLabel = ({
	children,
	className,
}: {
	children: string;
	className?: string;
}) => (
	<span className={className}>
		{children}
		{[0, 1, 2].map((i) => (
			<span
				key={i}
				className="inline-block animate-[dot-pulse_1.4s_ease-in-out_infinite]"
				style={{ animationDelay: `${i * 0.2}s` }}
			>
				.
			</span>
		))}
	</span>
);

/** The chain header before anything has arrived — same slot, type and
 *  padding as the `ChainOfThought` trigger, so "Thinking…" becomes
 *  "Working…" in place once the first step lands. Muted and shimmering on
 *  purpose: the task has not started yet. */
export const ChainThinking = ({ className }: { className?: string }) => (
	<div className={cn("flex w-full items-center gap-2.5 py-0.5", className)}>
		<Shimmer className="text-[13px] font-semibold">
			Thinking…
		</Shimmer>
	</div>
);

/** The 1px vertical rail steps hang on. Also used for nested subagent work. */
export const ChainRail = ({
	startAtFirstNode = false,
	className,
	children,
}: {
	/** Begin the line at the first node instead of the container's top edge —
	 *  for rails with no header above them (a subagent's band). */
	startAtFirstNode?: boolean;
	className?: string;
	children: ReactNode;
}) => (
	<div className={cn("relative", className)}>
		<span
			aria-hidden
			className={cn(
				"absolute bottom-2 left-[10px] w-px bg-rail dark:bg-white/10",
				startAtFirstNode ? "top-[17px]" : "top-0",
			)}
		/>
		{children}
	</div>
);

// ---------------------------------------------------------------------------
// Step nodes
// ---------------------------------------------------------------------------

/** 22px MCP favicon chip (fallback: first-letter tile). */
export const ChainStepIcon = ({
	icon,
	name,
}: {
	icon?: string | null;
	name: string;
}) => (
	<span className="relative z-[1] flex size-[22px] shrink-0 items-center justify-center rounded-[6px] border border-border bg-card">
		{icon ? (
			<Image
				unoptimized
				src={icon}
				alt={name}
				width={13}
				height={13}
				className="rounded-[2px]"
			/>
		) : (
			<span className="text-[10px] font-bold text-label dark:text-panel-dim">
				{name.charAt(0).toUpperCase()}
			</span>
		)}
	</span>
);

// ---------------------------------------------------------------------------
// ChainStep — one collapsible row on the rail
// ---------------------------------------------------------------------------

export type ChainStepProps = {
	/** 22px node sitting on the rail (favicon chip, emoji tile, ✦). */
	node: ReactNode;
	title: ReactNode;
	summary?: string;
	/** Right-side status (spinner, badge, elapsed). */
	meta?: ReactNode;
	/** Smaller type for one-level-nested subagent steps. */
	nested?: boolean;
	lockOpen?: boolean;
	onOpenChange?: (open: boolean) => void;
	className?: string;
	children?: ReactNode;
};

export const ChainStep = ({
	node,
	title,
	summary,
	meta,
	nested = false,
	lockOpen = false,
	onOpenChange,
	className,
	children,
}: ChainStepProps) => {
	const [userOpenPreference, setUserOpenPreference] = useState<boolean | null>(
		null,
	);
	const isOpen = lockOpen ? true : (userOpenPreference ?? false);

	const row = (
		<>
			{node}
			<span
				className={cn(
					"shrink-0 font-semibold text-foreground",
					nested ? "text-[13px]" : "text-[13.5px]",
				)}
			>
				{title}
			</span>
			{summary && (
				<span
					className={cn(
						"min-w-0 truncate text-muted-foreground",
						nested ? "text-[12.5px]" : "text-[13px]",
					)}
				>
					{summary}
				</span>
			)}
			<span className="ml-auto flex shrink-0 items-center gap-2 pl-2">
				{meta}
				{children != null && (
					<ChevronDownIcon className="size-3 text-ghost transition-transform duration-200 -rotate-90 group-data-[state=open]/step:rotate-0" />
				)}
			</span>
		</>
	);

	if (children == null) {
		return (
			<div
				className={cn(
					"relative flex w-full items-center gap-3 py-[7px]",
					className,
				)}
			>
				{row}
			</div>
		);
	}

	return (
		<Collapsible
			open={isOpen}
			onOpenChange={(open) => {
				setUserOpenPreference(open);
				onOpenChange?.(open);
			}}
			className={cn("group/step relative w-full min-w-0", className)}
		>
			<CollapsibleTrigger className="flex w-full cursor-pointer items-center gap-3 py-[7px] text-left">
				{row}
			</CollapsibleTrigger>
			<CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
				<div className="mb-2.5 ml-[34px] mt-1 flex min-w-0 flex-col gap-1.5">
					{children}
				</div>
			</CollapsibleContent>
		</Collapsible>
	);
};

// ---------------------------------------------------------------------------
// Expanded step content: mono-caps label + code/text block on the hover tint
// ---------------------------------------------------------------------------

export const StepSection = ({
	label,
	error = false,
	className,
	children,
}: {
	label: string;
	error?: boolean;
	className?: string;
	children: ReactNode;
}) => (
	<div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
		<div
			className={cn(
				"font-mono text-[9.5px] font-semibold tracking-[0.09em]",
				error ? "text-destructive" : "text-meta dark:text-panel-dim",
			)}
		>
			{label}
		</div>
		{children}
	</div>
);

/** JSON / text payload block: mono on white, hairline border, radius 6. */
export const StepCode = ({ value }: { value: unknown }) => {
	if (value == null) return null;

	if (typeof value === "string") {
		return (
			<div className="max-h-80 min-w-0 overflow-y-auto whitespace-pre-wrap rounded-[6px] border border-border bg-card px-3 py-2.5 font-mono text-[11.5px] leading-[1.7] text-body dark:text-panel-body">
				{value.replace(/\\n/g, "\n")}
			</div>
		);
	}

	const code = JSON.stringify(value, null, 2).replace(/\\n/g, "\n");
	if (code.length > SHIKI_MAX_CHARS) {
		return (
			<div className="max-h-80 min-w-0 overflow-y-auto whitespace-pre-wrap rounded-[6px] border border-border bg-card px-3 py-2.5 font-mono text-[11.5px] leading-[1.7] text-body dark:text-panel-body">
				{code}
			</div>
		);
	}
	return (
		<div className="max-h-80 min-w-0 overflow-y-auto rounded-[6px] border border-border bg-card">
			<CodeBlock code={code} language="json" />
		</div>
	);
};

/** Tinted band a step folds its nested work into (a subagent's own
 *  conversation). Mono `// LABEL` header, optional plain text under it (the
 *  task), then whatever hangs on the rail. */
export const ChainBand = ({
	label,
	text,
	className,
	children,
}: {
	label: string;
	text?: string;
	className?: string;
	children: ReactNode;
}) => (
	<div
		className={cn(
			"flex min-w-0 flex-col rounded-[10px] bg-hover/70 px-[18px] pb-4 pt-3.5 dark:bg-panel-card",
			className,
		)}
	>
		<div className="font-mono text-[10px] font-semibold tracking-[0.09em] text-meta dark:text-panel-dim">
			{"// "}
			{label}
		</div>
		{text && (
			<div className="mt-2 whitespace-pre-wrap font-mono text-[11px] leading-[1.55] text-label dark:text-panel-dim">
				{text}
			</div>
		)}
		<div className="mt-3 flex min-w-0 flex-col">{children}</div>
	</div>
);

/** 22px square node for a non-collapsible rail line — same tile as the
 *  root chain's reasoning step. */
export const ChainLineNode = ({
	className,
	children,
}: {
	className?: string;
	children: ReactNode;
}) => (
	<span
		className={cn(
			"relative z-[1] flex size-[22px] shrink-0 items-center justify-center rounded-[6px] border border-border bg-card text-[11px]",
			className,
		)}
	>
		{children}
	</span>
);

/** A plain (non-collapsible) line on the rail: a node and its text. */
export const ChainLine = ({
	node,
	className,
	children,
}: {
	node: ReactNode;
	className?: string;
	children: ReactNode;
}) => (
	<div className={cn("relative flex items-start gap-3 py-1.5", className)}>
		{node}
		<div className="min-w-0 flex-1 pt-[3px]">{children}</div>
	</div>
);

/** ✦ italic line for a subagent's own text on its nested rail. Rendered as
 *  markdown: its last line doubles as the subagent's result. */
export const ChainReasoningLine = ({
	text,
	streaming = false,
	className,
}: {
	text: string;
	/** Show a caret after the text while it is still arriving. */
	streaming?: boolean;
	className?: string;
}) => (
	<ChainLine
		className={className}
		node={<ChainLineNode className="text-petrol">✦</ChainLineNode>}
	>
		{/* The caret lives on this wrapper, not on MessageResponse: that one is
		    memoized on `children` alone, so a className flip with unchanged
		    text would never render and the caret would outlive the stream. */}
		<div
			className={cn(
				streaming &&
					"[&>*>*:last-child]:after:ml-0.5 [&>*>*:last-child]:after:inline-block [&>*>*:last-child]:after:h-3 [&>*>*:last-child]:after:w-1 [&>*>*:last-child]:after:animate-pulse [&>*>*:last-child]:after:rounded-sm [&>*>*:last-child]:after:bg-petrol [&>*>*:last-child]:after:align-text-bottom [&>*>*:last-child]:after:content-['']",
			)}
		>
			{/* The italic is the subagent's "voice" for prose; bold and markdown
			    headings (data-streamdown="heading-N") stay upright so a
			    structured result reads as a document, not as an aside. */}
			<MessageResponse className="text-[12.5px] italic leading-[1.6] text-muted-foreground [&_[data-streamdown=strong]]:not-italic [&_[data-streamdown=strong]]:text-foreground [&_[data-streamdown^=heading-]]:not-italic [&_[data-streamdown^=heading-]]:text-foreground">
				{text}
			</MessageResponse>
		</div>
	</ChainLine>
);

/** Amber approval badge for steps waiting on a human. */
export const NeedsApprovalBadge = () => (
	<span className="rounded-[4px] bg-warning-bg px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em] text-warning">
		NEEDS APPROVAL
	</span>
);

/** The model's reasoning as a step on the rail: open while it streams, folded
 *  behind its first line once done. */
export const ChainReasoningStep = ({
	text,
	streaming = false,
}: {
	text: string;
	streaming?: boolean;
}) => (
	<ChainStep
		node={
			<span className="relative z-[1] flex size-[22px] shrink-0 items-center justify-center rounded-[6px] border border-border bg-card text-[11px] text-petrol">
				✦
			</span>
		}
		title={
			streaming ? (
				// A quiet shimmer, no ellipsis: the header already carries the motion.
				<Shimmer
					duration={1.6}
					className="[--shimmer-color:var(--color-body)] dark:[--shimmer-color:var(--color-panel-body)]"
				>
					Reasoning
				</Shimmer>
			) : (
				"Reasoned"
			)
		}
		summary={text.split("\n").find((line) => line.trim()) ?? ""}
		meta={
			streaming ? (
				<Loader2 className="size-3 animate-spin text-petrol" />
			) : undefined
		}
		lockOpen={streaming}
	>
		<MessageResponse className="text-[12.5px] leading-[1.6] text-muted-foreground">
			{text}
		</MessageResponse>
	</ChainStep>
);

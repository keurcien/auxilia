"use client";

import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "lucide-react";
import Image from "next/image";
import type { ComponentProps, ReactNode } from "react";
import { useState } from "react";
import { CodeBlock, SHIKI_MAX_CHARS } from "./code-block";

// ---------------------------------------------------------------------------
// Petrol Mono chain of thought (design 8a): the agent's work renders as a
// mid-air timeline — a collapsible "✦ Worked" header, then steps hanging on
// a 1px rail. Tool calls and subagent calls are both steps.
// ---------------------------------------------------------------------------

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
	const record = args as Record<string, unknown>;
	for (const key of SUMMARY_ARG_PRIORITY) {
		const value = record[key];
		if (typeof value === "string" && value.trim()) return truncate(value);
	}
	for (const value of Object.values(record)) {
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
	const isOpen = lockOpen ? true : (userOpenPreference ?? active);

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
				<span className="flex size-[22px] shrink-0 items-center justify-center text-xs text-petrol">
					✦
				</span>
				<span className="text-[13px] font-semibold text-body dark:text-panel-body">
					{active ? "Working…" : "Worked"}
				</span>
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

/** The 1px vertical rail steps hang on. Also used for nested subagent work. */
export const ChainRail = ({
	className,
	children,
}: {
	className?: string;
	children: ReactNode;
}) => (
	<div className={cn("relative", className)}>
		<span
			aria-hidden
			className="absolute bottom-2 left-[10px] top-0 w-px bg-rail dark:bg-white/10"
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
	title: string;
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
	children,
}: {
	label: string;
	error?: boolean;
	children: ReactNode;
}) => (
	<div className="flex min-w-0 flex-col gap-1.5">
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

/** ✦ italic reasoning line (used inside subagent nested rails). */
export const ChainReasoningLine = ({
	children,
	className,
}: ComponentProps<"div">) => (
	<div className={cn("relative flex items-start gap-3 py-1.5", className)}>
		<span className="relative z-[1] flex size-[22px] shrink-0 items-center justify-center bg-background text-[11px] text-petrol">
			✦
		</span>
		<span className="min-w-0 whitespace-pre-wrap text-[12.5px] italic leading-[1.6] text-muted-foreground">
			{children}
		</span>
	</div>
);

/** Amber approval badge for steps waiting on a human. */
export const NeedsApprovalBadge = () => (
	<span className="rounded-[4px] bg-warning-bg px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em] text-warning">
		NEEDS APPROVAL
	</span>
);

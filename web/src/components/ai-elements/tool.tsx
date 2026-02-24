"use client";

import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import type { ToolUIPart } from "ai";
import {
	CheckIcon,
	ChevronDownIcon,
	CircleDashedIcon,
	LoaderIcon,
	XIcon,
} from "lucide-react";
import Image from "next/image";
import type { ComponentProps, ReactNode } from "react";
import { isValidElement, useState } from "react";
import { CodeBlock } from "./code-block";

export type ToolProps = ComponentProps<typeof Collapsible> & {
	toolState?: ToolUIPart["state"];
};

export const Tool = ({ className, toolState, ...props }: ToolProps) => {
	const [userOpenPreference, setUserOpenPreference] = useState<boolean | null>(
		null,
	);

	const isOpen =
		toolState === "approval-requested" ? true : (userOpenPreference ?? false);

	return (
		<Collapsible
			open={isOpen}
			onOpenChange={(open) => setUserOpenPreference(open)}
			className={cn(
				"not-prose group w-full min-w-0 overflow-hidden rounded-xl bg-muted/50 transition-colors hover:bg-muted/70",
				className,
			)}
			{...props}
		/>
	);
};

export type ToolHeaderProps = {
	title?: string;
	mcpServerName: string;
	mcpServerIcon?: string;
	type: ToolUIPart["type"];
	state: ToolUIPart["state"];
	approval?: ToolUIPart["approval"];
	className?: string;
};

const getStatusIcon = (
	status: ToolUIPart["state"],
	approval?: ToolUIPart["approval"],
): ReactNode => {
	switch (status) {
		case "input-streaming":
		// TO BE REFACTORED: corresponds to when tool_output is None
		// case "call":
		// 	return <CircleDashedIcon className="size-4 text-muted-foreground" />;
		case "input-available":
			return (
				<LoaderIcon className="size-4 text-muted-foreground animate-spin" />
			);
		case "output-available":
			return (
				<div className="flex items-center justify-center size-5 rounded-full bg-emerald-500/15">
					<CheckIcon className="size-3 text-emerald-500" strokeWidth={3} />
				</div>
			);
		case "approval-responded":
			// Optimistically show rejection state based on approval.approved
			if (approval?.approved === false) {
				return (
					<div className="flex items-center justify-center size-5 rounded-full bg-destructive/15">
						<XIcon className="size-3 text-destructive" strokeWidth={3} />
					</div>
				);
			}
			return (
				<div className="flex items-center justify-center size-5 rounded-full bg-emerald-500/15">
					<CheckIcon className="size-3 text-emerald-500" strokeWidth={3} />
				</div>
			);
		case "output-error":
		case "output-denied":
			return (
				<div className="flex items-center justify-center size-5 rounded-full bg-destructive/15">
					<XIcon className="size-3 text-destructive" strokeWidth={3} />
				</div>
			);
		case "approval-requested":
			return (
				<div className="flex items-center justify-center size-5 rounded-full bg-amber-500/15">
					<CircleDashedIcon className="size-3 text-amber-500" strokeWidth={3} />
				</div>
			);
		default:
			return null;
	}
};

export const ToolHeader = ({
	className,
	title,
	mcpServerName,
	mcpServerIcon,
	type,
	state,
	approval,
	...props
}: ToolHeaderProps) => {
	const toolName = title ?? type.split("-").slice(1).join("-");

	return (
		<CollapsibleTrigger
			className={cn(
				"flex w-full items-center justify-between gap-4 px-4 py-3 cursor-pointer",
				className,
			)}
			{...props}
		>
			<div className="flex items-center gap-3">
				{mcpServerIcon ? (
					<Image
						src={mcpServerIcon}
						alt={mcpServerName}
						width={20}
						height={20}
						className="rounded"
					/>
				) : (
					<div className="flex items-center justify-center size-5 rounded bg-foreground text-background text-xs font-bold">
						{mcpServerName.charAt(0).toUpperCase()}
					</div>
				)}
				<span className="font-medium text-sm text-muted-foreground">
					{mcpServerName}
				</span>
				<span className="font-medium text-sm text-primary">{toolName}</span>
			</div>
			<div className="flex items-center gap-2">
				{getStatusIcon(state, approval)}
				<ChevronDownIcon className="size-4 text-muted-foreground -rotate-90 transition-transform duration-200 ease-out group-data-[state=open]:rotate-0" />
			</div>
		</CollapsibleTrigger>
	);
};

export type ToolContentProps = ComponentProps<typeof CollapsibleContent>;

export const ToolContent = ({ className, ...props }: ToolContentProps) => (
	<CollapsibleContent
		className={cn(
			"w-full max-w-full min-w-0 overflow-hidden data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down",
			className,
		)}
		{...props}
	/>
);

export type ToolContentInnerProps = ComponentProps<"div">;

export const ToolContentInner = ({
	className,
	...props
}: ToolContentInnerProps) => (
	<div
		className={cn(
			"mx-3 mb-3 min-w-0 space-y-3 rounded-lg bg-background/50 border border-border/30 overflow-hidden",
			className,
		)}
		{...props}
	/>
);

export type ToolFooterProps = ComponentProps<"div">;

export const ToolFooter = ({ className, ...props }: ToolFooterProps) => (
	<div
		className={cn(
			"flex items-center justify-end gap-2 px-3 pb-3 pt-2",
			className,
		)}
		{...props}
	/>
);

export type ToolInputProps = ComponentProps<"div"> & {
	input: ToolUIPart["input"];
};

export const ToolInput = ({ className, input, ...props }: ToolInputProps) => (
	<div
		className={cn("min-w-0 space-y-2 overflow-hidden p-3", className)}
		{...props}
	>
		<h4 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
			Parameters
		</h4>
		<div className="min-w-0 overflow-hidden rounded-md bg-muted/60">
			<CodeBlock
				code={JSON.stringify(input, null, 2).replace(/\\n/g, "\n")}
				language="json"
			/>
		</div>
	</div>
);

export type ToolOutputProps = ComponentProps<"div"> & {
	output: ToolUIPart["output"];
	errorText: ToolUIPart["errorText"];
};

export const ToolOutput = ({
	className,
	output,
	errorText,
	...props
}: ToolOutputProps) => {
	if (!(output || errorText)) {
		return null;
	}

	const content = errorText ?? output;

	let Output: ReactNode = null;

	if (content != null) {
		if (typeof content === "object" && !isValidElement(content)) {
			Output = (
				<CodeBlock
					code={JSON.stringify(content, null, 2).replace(/\\n/g, "\n")}
					language="json"
				/>
			);
		} else if (typeof content === "string") {
			Output = (
				<CodeBlock code={content.replace(/\\n/g, "\n")} language="json" />
			);
		} else {
			Output = <div>{content as ReactNode}</div>;
		}
	}

	return (
		<div
			className={cn(
				"min-w-0 space-y-2 overflow-hidden p-3 border-t border-border/30",
				className,
			)}
			{...props}
		>
			<h4 className="font-medium text-muted-foreground text-xs uppercase tracking-wide">
				Result
			</h4>
			<div className="min-w-0 overflow-x-auto rounded-md bg-muted/60 text-foreground text-xs [&_table]:w-full max-h-80 overflow-y-auto">
				{Output}
			</div>
		</div>
	);
};

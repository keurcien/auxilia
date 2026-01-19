"use client";

import { useControllableState } from "@radix-ui/react-use-controllable-state";
import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { ChevronDownIcon } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { createContext, memo, useContext, useEffect, useState } from "react";
import { Streamdown } from "streamdown";
import { Shimmer } from "./shimmer";
import { Loader } from "@/components/ai-elements/loader";

type ReasoningContextValue = {
	isStreaming: boolean;
	isOpen: boolean;
	setIsOpen: (open: boolean) => void;
	duration: number | undefined;
};

const ReasoningContext = createContext<ReasoningContextValue | null>(null);

export const useReasoning = () => {
	const context = useContext(ReasoningContext);
	if (!context) {
		throw new Error("Reasoning components must be used within Reasoning");
	}
	return context;
};

export type ReasoningProps = ComponentProps<typeof Collapsible> & {
	isStreaming?: boolean;
	open?: boolean;
	defaultOpen?: boolean;
	onOpenChange?: (open: boolean) => void;
	duration?: number;
};

const AUTO_CLOSE_DELAY = 2000;
const MS_IN_S = 1000;

export const Reasoning = memo(
	({
		className,
		isStreaming = false,
		open,
		defaultOpen = false,
		onOpenChange,
		duration: durationProp,
		children,
		...props
	}: ReasoningProps) => {
		const [isOpen, setIsOpen] = useControllableState({
			prop: open,
			defaultProp: defaultOpen,
			onChange: onOpenChange,
		});
		const [duration, setDuration] = useControllableState({
			prop: durationProp,
			defaultProp: undefined,
		});

		const [hasAutoClosed, setHasAutoClosed] = useState(false);
		const [startTime, setStartTime] = useState<number | null>(null);

		// Track duration when streaming starts and ends
		useEffect(() => {
			if (isStreaming) {
				if (startTime === null) {
					setStartTime(Date.now());
				}
			} else if (startTime !== null) {
				setDuration(Math.ceil((Date.now() - startTime) / MS_IN_S));
				setStartTime(null);
			}
		}, [isStreaming, startTime, setDuration]);

		// Auto-open when streaming starts
		useEffect(() => {
			if (isStreaming) {
				setIsOpen(true);
			}
		}, [isStreaming, setIsOpen]);

		// Auto-close when streaming ends (once only)
		useEffect(() => {
			if (!isStreaming && isOpen && !hasAutoClosed) {
				const timer = setTimeout(() => {
					setIsOpen(false);
					setHasAutoClosed(true);
				}, AUTO_CLOSE_DELAY);

				return () => clearTimeout(timer);
			}
		}, [isStreaming, isOpen, defaultOpen, setIsOpen, hasAutoClosed]);

		const handleOpenChange = (newOpen: boolean) => {
			setIsOpen(newOpen);
		};

		return (
			<ReasoningContext.Provider
				value={{ isStreaming, isOpen, setIsOpen, duration }}
			>
				<Collapsible
					className={cn("not-prose", className)}
					onOpenChange={handleOpenChange}
					open={isOpen}
					{...props}
				>
					{children}
				</Collapsible>
			</ReasoningContext.Provider>
		);
	}
);

export type ReasoningTriggerProps = ComponentProps<
	typeof CollapsibleTrigger
> & {
	getThinkingMessage?: (isStreaming: boolean, duration?: number) => ReactNode;
};

const defaultGetThinkingMessage = (isStreaming: boolean, duration?: number) => {
	if (isStreaming || duration === 0) {
		return (
			<div className="flex flex-row gap-2 items-center">
				<Shimmer duration={1}>Reasoning...</Shimmer>
				<Loader size={16} className="animate-spin" />
			</div>
		);
	}
	if (duration === undefined) {
		return <p>Reasoned for a few seconds</p>;
	}
	return (
		<p>
			Reasoned for {duration} {duration === 1 ? "second" : "seconds"}
		</p>
	);
};

export const ReasoningTrigger = memo(
	({
		className,
		children,
		getThinkingMessage = defaultGetThinkingMessage,
		...props
	}: ReasoningTriggerProps) => {
		const { isStreaming, isOpen, duration } = useReasoning();

		return (
			<CollapsibleTrigger
				className={cn(
					"flex w-full items-center gap-2 text-muted-foreground text-sm transition-colors hover:text-foreground cursor-pointer",
					className
				)}
				{...props}
			>
				{children ?? (
					<>
						{getThinkingMessage(isStreaming, duration)}
						<ChevronDownIcon
							className={cn(
								"size-4 transition-transform",
								isOpen ? "rotate-0" : "-rotate-90"
							)}
						/>
					</>
				)}
			</CollapsibleTrigger>
		);
	}
);

export type ReasoningContentProps = ComponentProps<
	typeof CollapsibleContent
> & {
	children: string;
};

export const ReasoningContent = memo(
	({ className, children, ...props }: ReasoningContentProps) => {
		const { isOpen } = useReasoning();

		return (
			<div
				className={cn(
					"grid transition-[grid-template-rows] duration-300 ease-out",
					isOpen ? "grid-rows-[1fr]" : "grid-rows-[0fr]",
					"collapsible-content"
				)}
				{...props}
			>
				<div className="overflow-hidden">
					<div
						className={cn(
							"mt-4 text-sm border-l pl-3 text-muted-foreground outline-none",
							className
						)}
					>
						<Streamdown {...props}>{children}</Streamdown>
					</div>
				</div>
			</div>
		);
	}
);

Reasoning.displayName = "Reasoning";
ReasoningTrigger.displayName = "ReasoningTrigger";
ReasoningContent.displayName = "ReasoningContent";

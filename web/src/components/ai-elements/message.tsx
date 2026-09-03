"use client";

import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { ComponentProps, HTMLAttributes } from "react";
import { memo } from "react";
import { Streamdown } from "streamdown";

export type MessageProps = HTMLAttributes<HTMLDivElement> & {
	from: "user" | "assistant";
};

export const Message = ({ className, from, ...props }: MessageProps) => (
	<div
		className={cn(
			"group flex w-full flex-col gap-2",
			from === "user" ? "is-user ml-auto justify-end" : "is-assistant",
			className,
		)}
		{...props}
	/>
);

export type MessageContentProps = HTMLAttributes<HTMLDivElement>;

export const MessageContent = ({
	children,
	className,
	...props
}: MessageContentProps) => {
	const handleCopy = (e: React.ClipboardEvent) => {
		const selection = document.getSelection();
		if (selection) {
			const cleanText = selection
				.toString()
				.replace(/\n\s*\n/g, "\n")
				.trim();
			e.clipboardData.setData("text/plain", cleanText);
			e.preventDefault();
		}
	};
	return (
		<div
			onCopy={handleCopy}
			className={cn(
				"flex w-fit flex-col gap-2 overflow-hidden text-[14.5px] leading-[1.7]",
				"group-[.is-user]:ml-auto group-[.is-user]:rounded-[12px_12px_3px_12px] group-[.is-user]:bg-hover dark:group-[.is-user]:bg-secondary group-[.is-user]:px-4 group-[.is-user]:py-3 group-[.is-user]:leading-[1.6] group-[.is-user]:text-foreground group-[.is-user]:max-w-[78%]",
				"group-[.is-assistant]:text-foreground group-[.is-assistant]:w-full",
				className,
			)}
			{...props}
		>
			{children}
		</div>
	);
};

export type MessageActionsProps = ComponentProps<"div">;

export const MessageActions = ({
	className,
	children,
	...props
}: MessageActionsProps) => (
	<div className={cn("flex items-center gap-1", className)} {...props}>
		{children}
	</div>
);

export type MessageActionProps = ComponentProps<typeof Button> & {
	tooltip?: string;
	label?: string;
};

export const MessageAction = ({
	tooltip,
	children,
	label,
	variant = "ghost",
	size = "icon-sm",
	...props
}: MessageActionProps) => {
	const button = (
		<Button
			className="cursor-pointer"
			size={size}
			type="button"
			variant={variant}
			{...props}
		>
			{children}
			<span className="sr-only">{label || tooltip}</span>
		</Button>
	);

	if (tooltip) {
		return (
			<TooltipProvider>
				<Tooltip>
					<TooltipTrigger asChild>{button}</TooltipTrigger>
					<TooltipContent>
						<p>{tooltip}</p>
					</TooltipContent>
				</Tooltip>
			</TooltipProvider>
		);
	}

	return button;
};

export type MessageResponseProps = ComponentProps<typeof Streamdown>;

export const MessageResponse = memo(
	({ className, ...props }: MessageResponseProps) => (
		<Streamdown
			className={cn(
				"size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0",
				className,
			)}
			{...props}
		/>
	),
	(prevProps, nextProps) => prevProps.children === nextProps.children,
);

MessageResponse.displayName = "MessageResponse";

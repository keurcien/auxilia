"use client";

import { Button } from "@/components/ui/button";
import {
	Tooltip,
	TooltipContent,
	TooltipProvider,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { UIMessage } from "ai";
import type { ComponentProps, HTMLAttributes } from "react";
import { memo } from "react";
import { Streamdown } from "streamdown";

export type MessageProps = HTMLAttributes<HTMLDivElement> & {
	from: UIMessage["role"];
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
				"flex w-fit flex-col gap-2 overflow-hidden text-base leading-7",
				"group-[.is-user]:ml-auto group-[.is-user]:rounded-3xl group-[.is-user]:bg-[#F3F8F5] dark:group-[.is-user]:bg-[#1E2D28]/40 group-[.is-user]:px-4 group-[.is-user]:py-3 group-[.is-user]:text-[#1E2D28] dark:group-[.is-user]:text-white md:group-[.is-user]:max-w-[60%] group-[.is-user]:max-w-[80%]",
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

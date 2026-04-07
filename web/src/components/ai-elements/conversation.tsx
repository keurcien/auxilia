"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ArrowDownIcon } from "lucide-react";
import type { ComponentProps, FC } from "react";
import { useCallback } from "react";
import {
	StickToBottom as _StickToBottom,
	useStickToBottomContext,
	type StickToBottomProps,
} from "use-stick-to-bottom";

// React 19 compat: use-stick-to-bottom declares ReactNode return but JSX requires ReactElement | null
const StickToBottom = _StickToBottom as unknown as FC<StickToBottomProps> & {
	Content: FC<_StickToBottom.ContentProps>;
};

export type ConversationProps = StickToBottomProps;

export const Conversation = ({ className, ...props }: ConversationProps) => (
	<StickToBottom
		className={cn(
			"relative flex-1 min-h-0 [&>div]:[scrollbar-width:none] [&>div::-webkit-scrollbar]:hidden",
			className
		)}
		initial="smooth"
		resize="smooth"
		role="log"
		{...props}
	/>
);

export type ConversationContentProps = _StickToBottom.ContentProps;

export const ConversationContent = ({
	className,
	...props
}: ConversationContentProps) => (
	<StickToBottom.Content
		className={cn("flex flex-col gap-4 p-4", className)}
		{...props}
	/>
);

export type ConversationEmptyStateProps = ComponentProps<"div"> & {
	title?: string;
	description?: string;
	icon?: React.ReactNode;
};

export const ConversationEmptyState = ({
	className,
	title = "No messages yet",
	description = "Start a conversation to see messages here",
	icon,
	children,
	...props
}: ConversationEmptyStateProps) => (
	<div
		className={cn(
			"flex size-full flex-col items-center justify-center gap-3 p-8 text-center",
			className
		)}
		{...props}
	>
		{children ?? (
			<>
				{icon && <div className="text-muted-foreground">{icon}</div>}
				<div className="space-y-1">
					<h3 className="font-medium text-sm">{title}</h3>
					{description && (
						<p className="text-muted-foreground text-sm">{description}</p>
					)}
				</div>
			</>
		)}
	</div>
);

export type ConversationScrollButtonProps = ComponentProps<typeof Button>;

export const ConversationScrollButton = ({
	className,
	...props
}: ConversationScrollButtonProps) => {
	const { isAtBottom, scrollToBottom } = useStickToBottomContext();

	const handleScrollToBottom = useCallback(() => {
		scrollToBottom();
	}, [scrollToBottom]);

	if (isAtBottom) return null;

	return (
		<Button
			className={cn(
				"absolute bottom-4 left-[50%] translate-x-[-50%] rounded-full",
				className
			)}
			onClick={handleScrollToBottom}
			size="icon"
			type="button"
			variant="outline"
			{...props}
		>
			<ArrowDownIcon className="size-4" />
		</Button>
	);
};

"use client";

import { Check } from "lucide-react";

import { cn } from "@/lib/utils";

export function ConversationCompletionButton({
	completed,
	onToggle,
	disabled = false,
	className,
}: {
	completed: boolean;
	onToggle: () => void;
	disabled?: boolean;
	className?: string;
}) {
	return (
		<button
			type="button"
			disabled={disabled}
			aria-label={completed ? "Reopen conversation" : "Mark conversation as complete"}
			title={completed ? "Reopen conversation" : "Mark as complete"}
			onClick={(event) => {
				event.preventDefault();
				event.stopPropagation();
				onToggle();
			}}
			className={cn(
				"flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring disabled:cursor-wait disabled:opacity-50",
				completed
					? "border-emerald-600 bg-emerald-600 text-white"
					: "border-sidebar-muted-highlight bg-transparent text-transparent hover:border-sidebar-foreground",
				className,
			)}
		>
			<Check className="size-3" strokeWidth={3} />
		</button>
	);
}

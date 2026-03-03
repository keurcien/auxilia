"use client";

import { useChatHeaderStore } from "@/stores/chat-header-store";

export function ChatHeader() {
	const { agentName, agentEmoji } = useChatHeaderStore();

	if (!agentName) return null;

	return (
		<div className="w-full flex items-center justify-center gap-2">
			<div className="shrink-0 w-7 h-7 rounded-lg bg-muted text-sm flex items-center justify-center">
				{agentEmoji || "🤖"}
			</div>
			<span className="font-semibold text-sm">{agentName}</span>
		</div>
	);
}

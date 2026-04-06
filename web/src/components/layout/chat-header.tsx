"use client";

import { useChatHeaderStore } from "@/stores/chat-header-store";
import { agentColorBackground } from "@/lib/colors";

export function ChatHeader() {
	const { agentName, agentEmoji, agentColor } = useChatHeaderStore();

	if (!agentName) return null;

	return (
		<div className="w-full flex items-center justify-center gap-2">
			<div
				style={agentColor ? { background: agentColorBackground(agentColor) } : undefined}
				className={`shrink-0 w-7 h-7 rounded-lg text-sm flex items-center justify-center ${agentColor ? "" : "bg-muted"}`}
			>
				{agentEmoji || "🤖"}
			</div>
			<span className="font-semibold text-sm">{agentName}</span>
		</div>
	);
}

"use client";

import { useChatHeaderStore } from "@/stores/chat-header-store";
import { AgentAvatar } from "@/components/ui/agent-avatar";

export function ChatHeader() {
	const { agentName, agentEmoji, agentColor } = useChatHeaderStore();

	if (!agentName) return null;

	return (
		<div className="w-full flex items-center justify-center gap-2">
			<AgentAvatar color={agentColor} emoji={agentEmoji} size="xs" />
			<span className="font-[family-name:var(--font-dm-sans)] font-semibold text-[14px] text-[#1E2D28] dark:text-foreground">
				{agentName}
			</span>
		</div>
	);
}

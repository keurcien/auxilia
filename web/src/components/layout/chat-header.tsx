"use client";

import { AlarmClock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { formatRunAt } from "@/lib/triggers/schedule";
import { AgentAvatar } from "@/components/ui/agent-avatar";

/**
 * Petrol Mono chat header (design 8a): 56px, centered round avatar +
 * agent name, hairline bottom border like the other page top bars.
 */
export function ChatHeader() {
	const router = useRouter();
	const {
		agentName,
		agentEmoji,
		agentColor,
		triggerId,
		triggerName,
		triggerRunAt,
	} = useChatHeaderStore();

	if (triggerName) {
		return (
			<div className="flex h-14 shrink-0 items-center justify-center gap-2 border-b border-border px-5 text-[14px]">
				<div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-petrol-tint dark:bg-white/10">
					<AlarmClock className="size-3.5 text-petrol" />
				</div>
				{triggerId ? (
					<button
						type="button"
						onClick={() => {
							router.push(`/triggers/${triggerId}`);
						}}
						className="cursor-pointer rounded-sm font-semibold text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40"
					>
						{triggerName}
					</button>
				) : (
					<span className="font-semibold text-foreground">{triggerName}</span>
				)}
				{triggerRunAt && (
					<>
						<span className="text-ghost dark:text-panel-dim">/</span>
						<span className="font-mono text-[12px] text-meta dark:text-panel-dim">
							{formatRunAt(
								triggerRunAt,
								Intl.DateTimeFormat().resolvedOptions().timeZone,
							)}
						</span>
					</>
				)}
			</div>
		);
	}

	if (!agentName) return null;

	return (
		<div className="flex h-14 shrink-0 items-center justify-center gap-2 border-b border-border px-5">
			<AgentAvatar color={agentColor} emoji={agentEmoji} size="xs" />
			<span className="text-[14px] font-semibold tracking-[-0.01em] text-foreground">
				{agentName}
			</span>
		</div>
	);
}

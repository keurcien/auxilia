"use client";

import { AlarmClock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { formatRunAt } from "@/lib/triggers/schedule";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { SidebarTrigger } from "@/components/ui/sidebar";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import {
	AGENT_EDITOR_FORBIDDEN_MESSAGE,
	useOpenAgentEditor,
} from "@/hooks/use-open-agent-editor";

function MobileSidebarTrigger() {
	return (
		<SidebarTrigger className="absolute left-3 top-1/2 z-10 size-9 -translate-y-1/2 cursor-pointer rounded-lg border border-sidebar-border bg-sidebar shadow-raised md:hidden" />
	);
}

/**
 * Petrol Mono chat header (design 8a): 56px, centered round avatar +
 * agent name, hairline bottom border like the other page top bars. The agent
 * name leads to the agent's page, gated on `editor` there (the gate opens a
 * "No access" dialog when the viewer is too weak).
 */
export function ChatHeader() {
	const router = useRouter();
	const {
		agentId,
		agentName,
		agentEmoji,
		agentColor,
		agentImageRevision,
		triggerId,
		triggerName,
		triggerRunAt,
	} = useChatHeaderStore();
	const { openAgentEditor, forbiddenOpen, setForbiddenOpen } =
		useOpenAgentEditor();

	if (triggerName) {
		return (
			<div className="relative flex h-14 shrink-0 items-center justify-center border-b border-border px-14 text-[14px] md:px-5">
				<MobileSidebarTrigger />
				<div className="flex min-w-0 items-center justify-center gap-2">
					<div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-petrol-tint dark:bg-white/10">
						<AlarmClock className="size-3.5 text-petrol dark:text-panel-terminal" />
					</div>
					{triggerId ? (
						<button
							type="button"
							onClick={() => {
								router.push(`/triggers/${triggerId}`);
							}}
							className="cursor-pointer truncate rounded-sm font-semibold leading-none text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:hover:text-panel-terminal"
						>
							{triggerName}
						</button>
					) : (
						<span className="truncate font-semibold leading-none text-foreground">
							{triggerName}
						</span>
					)}
					{triggerRunAt && (
						<>
							<span className="text-ghost dark:text-panel-dim">/</span>
							<span className="truncate font-mono text-[12px] leading-none text-meta dark:text-panel-dim">
								{formatRunAt(
									triggerRunAt,
									Intl.DateTimeFormat().resolvedOptions().timeZone,
								)}
							</span>
						</>
					)}
				</div>
			</div>
		);
	}

	if (!agentName) {
		return (
			<div className="relative h-14 shrink-0 border-b border-border">
				<MobileSidebarTrigger />
			</div>
		);
	}

	return (
		<div className="relative flex h-14 shrink-0 items-center justify-center border-b border-border px-14 md:px-5">
			<MobileSidebarTrigger />
			<div className="flex min-w-0 items-center justify-center gap-2">
				<AgentAvatar
					agentId={agentId}
					name={agentName}
					imageRevision={agentImageRevision}
					color={agentColor}
					emoji={agentEmoji}
					size="xs"
				/>
				{agentId ? (
					<button
						type="button"
						onClick={() => {
							void openAgentEditor(agentId);
						}}
						className="cursor-pointer truncate rounded-sm text-[14px] font-semibold leading-none tracking-[-0.01em] text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:hover:text-panel-terminal"
					>
						{agentName}
					</button>
				) : (
					<span className="truncate text-[14px] font-semibold leading-none tracking-[-0.01em] text-foreground">
						{agentName}
					</span>
				)}
			</div>

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="No access"
				message={AGENT_EDITOR_FORBIDDEN_MESSAGE}
			/>
		</div>
	);
}

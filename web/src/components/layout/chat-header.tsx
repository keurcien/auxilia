"use client";

import { AlarmClock } from "lucide-react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { useModelsStore } from "@/stores/models-store";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import { formatRunAt } from "@/lib/triggers/schedule";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import {
	AGENT_EDITOR_FORBIDDEN_MESSAGE,
	useOpenAgentEditor,
} from "@/hooks/use-open-agent-editor";

/**
 * Renders its children in the chat header's right-hand slot (files, and later
 * cost, model…). A portal, so children keep the page's React context.
 */
export function ChatHeaderActions({ children }: { children: ReactNode }) {
	const el = useChatHeaderStore((state) => state.actionsEl);
	return el ? createPortal(children, el) : null;
}

function ActionsSlot() {
	const setActionsEl = useChatHeaderStore((state) => state.setActionsEl);
	const modelId = useChatHeaderStore((state) => state.modelId);
	const model = useModelsStore((state) =>
		state.models.find((m) => m.id === modelId),
	);
	return (
		// nowrap: the right gutter reserves the actions' full width, not their longest word.
		<div className="flex flex-none items-center gap-2 whitespace-nowrap pl-2">
			{modelId && (
				// Mirrors the composer's model pill (prompt-input composerPillClass).
				<span
					title={`Model: ${modelId}`}
					className="hidden h-[30px] max-w-56 items-center gap-2 rounded-full border border-border bg-white px-3 text-[13px] font-medium text-foreground @lg:flex dark:bg-white/5"
				>
					{model?.chefSlug && <ModelSelectorLogo provider={model.chefSlug} />}
					<span className="truncate">{model?.name ?? modelId}</span>
				</span>
			)}
			<div ref={setActionsEl} className="flex items-center gap-2" />
		</div>
	);
}

function HeaderBar({
	className,
	children,
}: {
	className?: string;
	children: ReactNode;
}) {
	return (
		// Equal flex-1 gutters centre the title; the right one never shrinks below
		// the actions, so a long title slides left, then truncates — no overlap.
		// @container: the model pill hides when the header itself is narrow.
		<div className="@container flex h-14 shrink-0 items-center border-b border-border px-5">
			<div className="flex-1 basis-0" />
			<div className={cn("flex min-w-0 items-center gap-2", className)}>
				{children}
			</div>
			<div className="flex flex-1 basis-0 justify-end">
				<ActionsSlot />
			</div>
		</div>
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
		triggerId,
		triggerName,
		triggerRunAt,
	} = useChatHeaderStore();
	const { openAgentEditor, forbiddenOpen, setForbiddenOpen } =
		useOpenAgentEditor();

	if (triggerName) {
		return (
			<HeaderBar className="text-[14px]">
				<div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-petrol-tint dark:bg-white/10">
					<AlarmClock className="size-3.5 text-petrol" />
				</div>
				{triggerId ? (
					<button
						type="button"
						onClick={() => {
							router.push(`/triggers/${triggerId}`);
						}}
						className="min-w-0 cursor-pointer truncate rounded-sm font-semibold text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40"
					>
						{triggerName}
					</button>
				) : (
					<span className="min-w-0 truncate font-semibold text-foreground">
						{triggerName}
					</span>
				)}
				{triggerRunAt && (
					<>
						<span className="text-ghost dark:text-panel-dim">/</span>
						<span className="flex-none whitespace-nowrap font-mono text-[12px] text-meta dark:text-panel-dim">
							{formatRunAt(
								triggerRunAt,
								Intl.DateTimeFormat().resolvedOptions().timeZone,
							)}
						</span>
					</>
				)}
			</HeaderBar>
		);
	}

	if (!agentName) return null;

	return (
		<HeaderBar>
			<span className="flex-none">
				<AgentAvatar color={agentColor} emoji={agentEmoji} size="xs" />
			</span>
			{agentId ? (
				<button
					type="button"
					onClick={() => {
						void openAgentEditor(agentId);
					}}
					className="min-w-0 cursor-pointer truncate rounded-sm text-[14px] font-semibold tracking-[-0.01em] text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40"
				>
					{agentName}
				</button>
			) : (
				<span className="min-w-0 truncate text-[14px] font-semibold tracking-[-0.01em] text-foreground">
					{agentName}
				</span>
			)}

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="No access"
				message={AGENT_EDITOR_FORBIDDEN_MESSAGE}
			/>
		</HeaderBar>
	);
}

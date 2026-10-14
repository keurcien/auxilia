"use client";

import { AlarmClock } from "lucide-react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { useModelsStore } from "@/stores/models-store";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import {
	HoverCard,
	HoverCardContent,
	HoverCardTrigger,
} from "@/components/ui/hover-card";
import type { ThreadCost } from "@/lib/api/resources/thread-costs";
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

/** Pill amount: two decimals, `< 0.01$` (thin space) under a cent. */
export function formatPillCost(amount: string): string {
	const value = Number(amount);
	return value > 0 && value < 0.01 ? "<\u20090.01$" : `${value.toFixed(2)}$`;
}

/** Hover amount: the exact value (up to 10 decimals; the API may send `0E-7`). */
export function formatExactCost(amount: string): string {
	return `${Number(amount).toLocaleString("en-US", { maximumFractionDigits: 10 })}$`;
}

function CostBreakdown({ cost }: { cost: ThreadCost }) {
	const rows = [
		["Input", cost.usageDetails.input, cost.costDetails.input],
		["Cached input", cost.usageDetails.inputCacheRead, cost.costDetails.inputCacheRead],
		["Cache write", cost.usageDetails.inputCacheCreation, cost.costDetails.inputCacheCreation],
		["Output", cost.usageDetails.output, cost.costDetails.output],
	] as const;
	return (
		<div className="text-[12px]">
			<table className="w-full tabular-nums">
				<thead>
					<tr className="text-meta">
						<th className="pb-1 text-left font-medium" />
						<th className="pb-1 text-right font-medium">Tokens</th>
						<th className="pb-1 pl-4 text-right font-medium">Cost</th>
					</tr>
				</thead>
				<tbody>
					{rows.map(([label, tokens, amount]) => (
						<tr key={label}>
							<td className="py-0.5 text-subtle">{label}</td>
							<td className="py-0.5 text-right">{tokens.toLocaleString("en-US")}</td>
							<td className="py-0.5 pl-4 text-right font-mono">{formatExactCost(amount)}</td>
						</tr>
					))}
					<tr className="border-t border-border font-semibold">
						<td className="pt-1.5">Total</td>
						<td className="pt-1.5 text-right">
							{cost.usageDetails.total.toLocaleString("en-US")}
						</td>
						<td className="pt-1.5 pl-4 text-right font-mono">
							{formatExactCost(cost.costDetails.total)}
						</td>
					</tr>
				</tbody>
			</table>
			{!cost.complete && (
				<p className="mt-2 text-meta">
					{cost.unpricedCallCount} of {cost.callCount} calls have no price or usage; the
					total covers the priced calls only.
				</p>
			)}
		</div>
	);
}

function ActionsSlot() {
	const setActionsEl = useChatHeaderStore((state) => state.setActionsEl);
	const modelId = useChatHeaderStore((state) => state.modelId);
	const model = useModelsStore((state) =>
		state.models.find((m) => m.id === modelId),
	);
	const cost = useChatHeaderStore((state) => state.cost);
	const showCost = cost !== null && cost.callCount > 0;
	const pill = modelId && (
		// Mirrors the composer's model pill (prompt-input composerPillClass).
		<span
			title={showCost ? undefined : `Model: ${modelId}`}
			// Focusable when it opens the breakdown: the hover card also opens on focus.
			tabIndex={showCost ? 0 : undefined}
			className="hidden h-[30px] max-w-72 items-center gap-2 rounded-full border border-border bg-white px-3 text-[13px] font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 @lg:flex dark:bg-white/5"
		>
			{model?.chefSlug && <ModelSelectorLogo provider={model.chefSlug} />}
			<span className="truncate">{model?.name ?? modelId}</span>
			{showCost && (
				// 7ch fits "999.99$", so the pill doesn't jump as the cost grows.
				<span className="min-w-[7ch] flex-none border-l border-border pl-2 text-right tabular-nums text-subtle">
					{formatPillCost(cost.knownCost)}
				</span>
			)}
		</span>
	);
	return (
		// nowrap: the right gutter reserves the actions' full width, not their longest word.
		<div className="flex flex-none items-center gap-2 whitespace-nowrap pl-2">
			{showCost ? (
				<HoverCard openDelay={150} closeDelay={100}>
					<HoverCardTrigger asChild>{pill}</HoverCardTrigger>
					<HoverCardContent align="end" className="w-80">
						<CostBreakdown cost={cost} />
					</HoverCardContent>
				</HoverCard>
			) : (
				pill
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

"use client";

import {
	AlarmClock,
	Bell,
	BellOff,
	Brain,
	LoaderCircle,
	MoreHorizontal,
	Settings2,
} from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { useModelsStore } from "@/stores/models-store";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import {
	HoverCard,
	HoverCardContent,
	HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import type { ThreadCost } from "@/lib/api/resources/thread-costs";
import { formatRunAt } from "@/lib/triggers/schedule";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { SidebarTrigger, useSidebar } from "@/components/ui/sidebar";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import {
	AGENT_EDITOR_FORBIDDEN_MESSAGE,
	useOpenAgentEditor,
} from "@/hooks/use-open-agent-editor";
import {
	Sheet,
	SheetContent,
	SheetDescription,
	SheetHeader,
	SheetTitle,
} from "@/components/ui/sheet";
import type { ThreadNotifications } from "@/hooks/use-thread-notifications";
import { useEdgeSwipe } from "@/hooks/use-edge-swipe";
import { Switch } from "@/components/ui/switch";
import type { WebPushState } from "@/types/web-push";

/** Pill amount: two decimals, or less than one cent. */
export function formatPillCost(amount: string): string {
	const value = Number(amount);
	return value > 0 && value < 0.01 ? "<\u20090.01$" : `${value.toFixed(2)}$`;
}

/** Hover amount: retain useful precision for small per-token totals. */
export function formatExactCost(amount: string): string {
	return `${Number(amount).toLocaleString("en-US", {
		maximumFractionDigits: 10,
	})}$`;
}

function CostBreakdown({ cost }: { cost: ThreadCost }) {
	if (cost.unpricedCallCount === cost.callCount) {
		return (
			<div className="text-[12px]">
				<p className="font-semibold text-foreground">Cost unavailable</p>
				<p className="mt-1 leading-5 text-meta">
					Token usage or catalog pricing was not retained for these calls. New
					compatible model calls will include usage automatically.
				</p>
			</div>
		);
	}
	const rows = [
		["Input", cost.usageDetails.input, cost.costDetails.input],
		[
			"Cached input",
			cost.usageDetails.inputCacheRead,
			cost.costDetails.inputCacheRead,
		],
		[
			"Cache write",
			cost.usageDetails.inputCacheCreation,
			cost.costDetails.inputCacheCreation,
		],
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
							<td className="py-0.5 text-right">
								{tokens.toLocaleString("en-US")}
							</td>
							<td className="py-0.5 pl-4 text-right font-mono">
								{formatExactCost(amount)}
							</td>
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
					{cost.unpricedCallCount} of {cost.callCount} calls have no price or
					usage; this subtotal covers priced calls only.
				</p>
			)}
		</div>
	);
}

function ModelCostPill() {
	const modelId = useChatHeaderStore((state) => state.modelId);
	const cost = useChatHeaderStore((state) => state.cost);
	const model = useModelsStore((state) =>
		state.models.find((candidate) => candidate.id === modelId),
	);
	if (!modelId) return null;

	const showCost = cost !== null && cost.callCount > 0;
	const costUnavailable = showCost && cost.unpricedCallCount === cost.callCount;
	const costLabel = costUnavailable
		? "Unavailable"
		: showCost
			? `${cost.complete ? "" : "≥"}${formatPillCost(cost.knownCost)}`
			: null;
	const pill = (
		<span
			title={showCost ? undefined : `Model: ${modelId}`}
			tabIndex={showCost ? 0 : undefined}
			className="hidden h-[30px] min-w-0 max-w-72 items-center gap-2 rounded-full border border-border bg-white px-3 text-[13px] font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 md:flex dark:bg-white/5"
		>
			{model?.chefSlug && <ModelSelectorLogo provider={model.chefSlug} />}
			<span className="truncate">{model?.name ?? modelId}</span>
			{showCost && (
				<span className="flex-none border-l border-border pl-2 text-right tabular-nums text-subtle">
					{costLabel}
				</span>
			)}
		</span>
	);
	return showCost ? (
		<HoverCard openDelay={150} closeDelay={100}>
			<HoverCardTrigger asChild>{pill}</HoverCardTrigger>
			<HoverCardContent align="end" className="w-80">
				<CostBreakdown cost={cost} />
			</HoverCardContent>
		</HoverCard>
	) : (
		pill
	);
}

function MobileSidebarTrigger() {
	return (
		<SidebarTrigger className="absolute left-3 top-1/2 z-10 size-9 -translate-y-1/2 cursor-pointer rounded-lg border border-sidebar-border bg-sidebar shadow-raised md:hidden" />
	);
}

export function ChatHeaderActions({
	children,
	mobileOnly = false,
}: {
	children: ReactNode;
	mobileOnly?: boolean;
}) {
	const element = useChatHeaderStore((state) => state.actionsEl);
	return element
		? createPortal(
				<div className={mobileOnly ? "contents md:hidden" : "hidden md:contents"}>
					{children}
				</div>,
				element,
			)
		: null;
}

export function ChatHeaderLeadingActions({
	children,
}: {
	children: ReactNode;
}) {
	const element = useChatHeaderStore((state) => state.leadingActionsEl);
	return element ? createPortal(children, element) : null;
}

export function ChatMobileActionsSheet({
	children,
}: {
	children: ReactNode;
}) {
	const [open, setOpen] = useState(false);
	const { isMobile } = useSidebar();
	const openMobileActions = useCallback(() => {
		setOpen(true);
	}, []);

	const {
		contentRef,
		contentStyle,
		gestureControlled,
		handleSheetOpenChange,
		overlayStyle,
	} = useEdgeSwipe({
		edge: "right",
		enabled: isMobile,
		open,
		onOpenChange: setOpen,
	});

	return (
		<Sheet open={open} onOpenChange={handleSheetOpenChange}>
			<ChatHeaderActions mobileOnly>
				<button
					type="button"
					onClick={openMobileActions}
					aria-label="Open conversation options"
					className="flex size-9 cursor-pointer items-center justify-center rounded-lg border border-sidebar-border bg-sidebar text-sidebar-muted shadow-raised transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
				>
					<MoreHorizontal className="size-4.5" />
				</button>
			</ChatHeaderActions>
			<SheetContent
				ref={contentRef}
				side="right"
				data-gesture-controlled={gestureControlled || undefined}
				className="w-72 max-w-72 gap-0 border-sidebar-border bg-sidebar p-0 sm:max-w-72"
				overlayStyle={overlayStyle}
				style={contentStyle}
			>
				<SheetHeader className="border-b border-sidebar-border px-5 py-5 pr-12">
					<SheetTitle className="text-[18px]">Conversation options</SheetTitle>
					<SheetDescription className="text-[14px] leading-5">
						Manage this conversation and its sharing settings.
					</SheetDescription>
				</SheetHeader>
				<div className="overflow-y-auto p-5">{children}</div>
			</SheetContent>
		</Sheet>
	);
}

export function ChatMemoryToggle({
	enabled,
	disabled,
	saving,
	onChange,
}: {
	enabled: boolean;
	disabled?: boolean;
	saving?: boolean;
	onChange: (enabled: boolean) => void;
}) {
	const label = enabled
		? "Memories enabled for this conversation"
		: "Memories disabled for this conversation";
	return (
		<div
			className={`flex h-[30px] items-center overflow-hidden rounded-full border text-[11.5px] font-semibold transition-colors ${
				enabled
					? "border-petrol/25 bg-petrol/8 text-petrol dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal"
					: "border-border bg-card text-meta dark:bg-white/5"
			}`}
		>
			<Tooltip>
				<TooltipTrigger asChild>
					<button
						type="button"
						aria-label={label}
						aria-pressed={enabled}
						disabled={disabled || saving}
						onClick={() => {
							onChange(!enabled);
						}}
						className="flex h-full cursor-pointer items-center gap-1.5 px-2.5 transition-colors hover:bg-black/5 hover:text-foreground disabled:cursor-default disabled:opacity-45 dark:hover:bg-white/5"
					>
						{saving ? (
							<LoaderCircle className="size-3.5 animate-spin" />
						) : (
							<Brain className="size-3.5" />
						)}
						<span className="hidden lg:inline">Memories</span>
						<span
							className={`hidden size-1.5 rounded-full lg:block ${
								enabled ? "bg-current" : "bg-meta/50"
							}`}
						/>
					</button>
				</TooltipTrigger>
				<TooltipContent side="bottom" sideOffset={7}>
					{label}
				</TooltipContent>
			</Tooltip>
			<Tooltip>
				<TooltipTrigger asChild>
					<Link
						href="/settings?tab=profile&section=memories"
						aria-label="Open memory settings"
						className="flex h-full w-6 items-center justify-center border-l border-current/15 opacity-65 transition-colors hover:bg-black/5 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none dark:hover:bg-white/5"
					>
						<Settings2 className="size-3" />
					</Link>
				</TooltipTrigger>
				<TooltipContent side="bottom" sideOffset={7}>
					Open memory settings
				</TooltipContent>
			</Tooltip>
		</div>
	);
}

function threadNotificationsLabel(
	enabled: boolean,
	webPushState: WebPushState,
): string {
	if (!enabled) return "Notifications are off for this conversation";
	if (webPushState === "denied") {
		return "Notifications are on for this conversation, but this browser blocks them";
	}
	if (webPushState === "disabled" || webPushState === "unsupported") {
		return "Notifications are on for this conversation, but not on this browser";
	}
	if (webPushState === "not-configured") {
		return "Notifications are on for this conversation, but push is not configured on this server";
	}
	return "Notifications are on for this conversation";
}

export function ChatMobileNotificationsRow({
	notifications: { enabled, saving, webPushState, setEnabled },
}: {
	notifications: ThreadNotifications;
}) {
	return (
		<div className="border-t border-sidebar-border px-4 py-3">
			<div className="flex min-h-10 items-center justify-between gap-4">
				<span className="flex min-w-0 items-center gap-2.5 text-[15px] font-semibold text-sidebar-foreground">
					{saving ? (
						<LoaderCircle className="size-[18px] shrink-0 animate-spin text-sidebar-active-icon" />
					) : enabled ? (
						<Bell className="size-[18px] shrink-0 text-sidebar-active-icon" />
					) : (
						<BellOff className="size-[18px] shrink-0 text-sidebar-muted" />
					)}
					Notifications
				</span>
				<Switch
					className="h-6 w-11 [&_[data-slot=switch-thumb]]:size-5 [&[data-state=checked]_[data-slot=switch-thumb]]:translate-x-5"
					checked={enabled}
					disabled={saving}
					aria-label="Notifications for this conversation"
					onCheckedChange={(checked) => {
						void setEnabled(checked);
					}}
				/>
			</div>
			<p className="mt-1 text-[13px] leading-5 text-sidebar-muted">
				{threadNotificationsLabel(enabled, webPushState)}.
			</p>
		</div>
	);
}

export function ChatNotificationsToggle({
	notifications: { enabled, saving, webPushState, setEnabled },
}: {
	notifications: ThreadNotifications;
}) {
	const label = threadNotificationsLabel(enabled, webPushState);
	return (
		<div
			className={`flex h-[30px] items-center overflow-hidden rounded-full border text-[11.5px] font-semibold transition-colors ${
				enabled
					? "border-petrol/25 bg-petrol/8 text-petrol dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal"
					: "border-border bg-card text-meta dark:bg-white/5"
			}`}
		>
			<Tooltip>
				<TooltipTrigger asChild>
					<button
						type="button"
						role="switch"
						aria-label="Notifications for this conversation"
						aria-checked={enabled}
						disabled={saving}
						onClick={() => {
							void setEnabled(!enabled);
						}}
						className="flex h-full cursor-pointer items-center gap-1.5 px-2.5 transition-colors hover:bg-black/5 hover:text-foreground disabled:cursor-wait disabled:opacity-45 dark:hover:bg-white/5"
					>
						{saving ? (
							<LoaderCircle className="size-3.5 animate-spin" />
						) : enabled ? (
							<Bell className="size-3.5" />
						) : (
							<BellOff className="size-3.5" />
						)}
						<span className="hidden xl:inline">Notifications</span>
						<span
							className={`hidden size-1.5 rounded-full xl:block ${
								enabled ? "bg-current" : "bg-meta/50"
							}`}
						/>
					</button>
				</TooltipTrigger>
				<TooltipContent side="bottom" sideOffset={7}>
					{label}
				</TooltipContent>
			</Tooltip>
			<Tooltip>
				<TooltipTrigger asChild>
					<Link
						href="/settings?tab=profile&section=preferences"
						aria-label="Default for new conversations"
						className="flex h-full w-6 items-center justify-center border-l border-current/15 opacity-65 transition-colors hover:bg-black/5 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none dark:hover:bg-white/5"
					>
						<Settings2 className="size-3" />
					</Link>
				</TooltipTrigger>
				<TooltipContent side="bottom" sideOffset={7}>
					Default for new conversations
				</TooltipContent>
			</Tooltip>
		</div>
	);
}

function HeaderActionsSlot() {
	const setActionsEl = useChatHeaderStore((state) => state.setActionsEl);
	return <div ref={setActionsEl} className="flex min-w-0 items-center gap-2" />;
}

function HeaderLeadingActionsSlot() {
	const setLeadingActionsEl = useChatHeaderStore(
		(state) => state.setLeadingActionsEl,
	);
	return (
		<div
			ref={setLeadingActionsEl}
			className="col-start-1 hidden min-w-0 items-center gap-2 md:flex"
		/>
	);
}

function HeaderBar({
	children,
	className,
}: {
	children?: ReactNode;
	className?: string;
}) {
	return (
		<div className="relative grid h-14 shrink-0 grid-cols-[44px_minmax(0,1fr)_auto] items-center border-b border-border px-3 md:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] md:px-5">
			<MobileSidebarTrigger />
			<HeaderLeadingActionsSlot />
			<div
				className={`col-start-2 flex min-w-0 items-center justify-center gap-2 ${className ?? ""}`}
			>
				{children}
			</div>
			<div className="col-start-3 flex min-w-0 items-center gap-1 justify-self-end md:gap-2">
				<ModelCostPill />
				<HeaderActionsSlot />
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
		agentImageRevision,
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
					<AlarmClock className="size-3.5 text-petrol dark:text-panel-terminal" />
				</div>
				{triggerId ? (
					<button
						type="button"
						onClick={() => {
							router.push(`/triggers/${triggerId}`);
						}}
						className="min-w-0 cursor-pointer truncate rounded-sm font-semibold leading-none text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:hover:text-panel-terminal"
					>
						{triggerName}
					</button>
				) : (
					<span className="min-w-0 truncate font-semibold leading-none text-foreground">
						{triggerName}
					</span>
				)}
				{triggerRunAt && (
					<span className="hidden md:contents">
						<span className="text-ghost dark:text-panel-dim">/</span>
						<span className="flex-none whitespace-nowrap font-mono text-[12px] leading-none text-meta dark:text-panel-dim">
							{formatRunAt(
								triggerRunAt,
								Intl.DateTimeFormat().resolvedOptions().timeZone,
							)}
						</span>
					</span>
				)}
			</HeaderBar>
		);
	}

	if (!agentName) {
		return <HeaderBar />;
	}

	return (
		<HeaderBar>
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
					className="min-w-0 cursor-pointer truncate rounded-sm text-[14px] font-semibold leading-none tracking-[-0.01em] text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:hover:text-panel-terminal"
				>
					{agentName}
				</button>
			) : (
				<span className="min-w-0 truncate text-[14px] font-semibold leading-none tracking-[-0.01em] text-foreground">
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

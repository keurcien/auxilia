"use client";

import {
	AlarmClock,
	Bell,
	BellOff,
	Brain,
	Cpu,
	Folder,
	FolderInput,
	LoaderCircle,
	MoreHorizontal,
	Settings2,
} from "lucide-react";
import {
	createContext,
	useCallback,
	useContext,
	useEffect,
	useMemo,
	useState,
	type ReactElement,
	type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import {
	type ChatHeaderProject,
	useChatHeaderStore,
} from "@/stores/chat-header-store";
import { useModelsStore } from "@/stores/models-store";
import { useProjectsStore } from "@/stores/projects-store";
import { getProjectFolderPath } from "@/lib/project-folders";
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

/** Round, icon-only header action; `active` tints it petrol. */
export function headerIconButtonClass(active = false): string {
	return `relative flex size-[30px] shrink-0 cursor-pointer items-center justify-center rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
		active
			? "border-petrol/25 bg-petrol/8 text-petrol hover:bg-petrol/12 dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal"
			: "border-border bg-card text-meta hover:bg-hover hover:text-foreground dark:bg-white/5"
	}`;
}

/**
 * The label of an icon-only header action: a bold name, plus an optional
 * line saying what it does or why it is unavailable.
 */
export function HeaderTip({
	label,
	hint,
	children,
}: {
	label: ReactNode;
	hint?: ReactNode;
	children: ReactElement;
}) {
	return (
		<Tooltip delayDuration={120}>
			<TooltipTrigger asChild>{children}</TooltipTrigger>
			<TooltipContent
				side="bottom"
				sideOffset={8}
				className="max-w-[260px] rounded-[9px] px-3 py-2 text-left shadow-[0_10px_30px_rgba(12,20,17,0.22)]"
			>
				<span className="block text-[12px] font-semibold leading-4">{label}</span>
				{hint && (
					<span className="mt-0.5 block text-[11px] leading-[15px] text-background/70">
						{hint}
					</span>
				)}
			</TooltipContent>
		</Tooltip>
	);
}

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

function useHeaderModelCost() {
	const modelId = useChatHeaderStore((state) => state.modelId);
	const cost = useChatHeaderStore((state) => state.cost);
	const model = useModelsStore((state) =>
		state.models.find((candidate) => candidate.id === modelId),
	);
	const showCost = cost !== null && cost.callCount > 0;
	const costLabel = !showCost
		? null
		: cost.unpricedCallCount === cost.callCount
			? "Unavailable"
			: `${cost.complete ? "" : "≥"}${formatPillCost(cost.knownCost)}`;
	return { modelId, model, cost: showCost ? cost : null, costLabel };
}

function ModelCostPill() {
	const { modelId, model, cost, costLabel } = useHeaderModelCost();
	if (!modelId) return null;

	const showCost = cost !== null;
	const name = model?.name ?? modelId;
	const pill = (
		<span
			tabIndex={0}
			aria-label={showCost ? `Model ${name}, cost ${costLabel}` : `Model ${name}`}
			className={`hidden h-[30px] shrink-0 items-center gap-2 rounded-full border border-border bg-white text-[13px] font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 md:flex dark:bg-white/5 ${
				showCost ? "pl-2 pr-3" : "w-[30px] justify-center"
			}`}
		>
			{model?.chefSlug ? (
				<ModelSelectorLogo provider={model.chefSlug} />
			) : (
				<Cpu className="size-3.5 text-meta" />
			)}
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
				<div className="mb-3 flex items-center gap-2 border-b border-border pb-2.5 text-[12.5px] font-semibold text-foreground">
					{model?.chefSlug && <ModelSelectorLogo provider={model.chefSlug} />}
					<span className="min-w-0 truncate">{name}</span>
				</div>
				<CostBreakdown cost={cost} />
			</HoverCardContent>
		</HoverCard>
	) : (
		<HeaderTip label={name} hint="Model used in this conversation">
			{pill}
		</HeaderTip>
	);
}

function ChatMobileModelCost() {
	const { modelId, model, cost, costLabel } = useHeaderModelCost();
	if (!modelId) return null;
	return (
		<section className="mb-6">
			<div className="mb-2 px-1">
				<h2 className="font-display text-[15px] font-semibold text-sidebar-foreground">
					Model and cost
				</h2>
			</div>
			<div className="overflow-hidden rounded-[12px] border border-sidebar-border bg-card">
				<div className="flex min-h-14 items-center gap-2.5 px-4 py-2.5 text-[15px] font-semibold text-sidebar-foreground">
					{model?.chefSlug && <ModelSelectorLogo provider={model.chefSlug} />}
					<span className="min-w-0 truncate">{model?.name ?? modelId}</span>
					{costLabel && (
						<span className="ml-auto flex-none tabular-nums text-sidebar-muted">
							{costLabel}
						</span>
					)}
				</div>
				<div className="border-t border-sidebar-border px-4 py-3">
					{cost ? (
						<CostBreakdown cost={cost} />
					) : (
						<p className="text-[13.5px] leading-5 text-sidebar-muted">
							No model calls recorded yet.
						</p>
					)}
				</div>
			</div>
		</section>
	);
}

/**
 * Publishes the conversation's project to the header. A project the viewer
 * cannot see resolves to none.
 */
export function useChatHeaderProject(
	projectId: string | null,
	folderId: string | null,
) {
	const tree = useProjectsStore((state) => state.tree);
	const setProject = useChatHeaderStore((state) => state.setProject);
	const project = useMemo<ChatHeaderProject | null>(() => {
		const match = projectId
			? tree.find((candidate) => candidate.id === projectId)
			: undefined;
		if (!match) return null;
		const folder = folderId
			? match.folders.find((candidate) => candidate.id === folderId)
			: undefined;
		return {
			id: match.id,
			name: match.name,
			emoji: match.emoji,
			folderPath: folder ? getProjectFolderPath(folder, match.folders) : null,
			href: folder
				? `/projects/${match.id}?folder=${folder.id}`
				: `/projects/${match.id}`,
		};
	}, [folderId, projectId, tree]);
	useEffect(() => {
		setProject(project);
	}, [project, setProject]);
	useEffect(
		() => () => {
			setProject(null);
		},
		[setProject],
	);
}

function ProjectGlyph({
	emoji,
	className,
}: {
	emoji: string | null;
	className?: string;
}) {
	return emoji ? (
		<span aria-hidden className="shrink-0 leading-none">
			{emoji}
		</span>
	) : (
		<Folder className={`shrink-0 text-petrol dark:text-panel-terminal ${className ?? ""}`} />
	);
}

/**
 * Breadcrumb leading the header title: project, then folder. Desktop only
 * beside a title; `standalone` (no title yet) shows it everywhere.
 */
function ProjectCrumb({ standalone = false }: { standalone?: boolean }) {
	const project = useChatHeaderStore((state) => state.project);
	if (!project) return null;
	const label = project.folderPath
		? `${project.name} / ${project.folderPath}`
		: project.name;
	return (
		<span
			className={
				standalone
					? "flex min-w-0 max-w-72 items-center"
					: "hidden min-w-0 max-w-64 shrink items-center gap-2 md:flex"
			}
		>
			<Tooltip>
				<TooltipTrigger asChild>
					<Link
						href={project.href}
						aria-label={`Open project ${label}`}
						className="flex min-w-0 items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-[12.5px] font-semibold text-subtle transition-colors hover:border-petrol/30 hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:bg-white/5 dark:text-muted-foreground dark:hover:text-panel-terminal"
					>
						<ProjectGlyph emoji={project.emoji} className="size-3.5" />
						<span className="truncate">{project.name}</span>
						{project.folderPath && (
							<span className="hidden min-w-0 truncate font-medium text-meta lg:inline dark:text-panel-dim">
								/ {project.folderPath}
							</span>
						)}
					</Link>
				</TooltipTrigger>
				<TooltipContent side="bottom" sideOffset={7}>
					Open project
				</TooltipContent>
			</Tooltip>
			{!standalone && (
				<span aria-hidden className="text-ghost dark:text-panel-dim">
					/
				</span>
			)}
		</span>
	);
}

export function ChatMoveToProjectButton({ onMove }: { onMove: () => void }) {
	const inProject = useChatHeaderStore((state) => state.project !== null);
	const label = inProject ? "Move to another project" : "Move to project";
	return (
		<HeaderTip
			label="Move"
			hint={inProject ? "File this conversation in another project" : "File this conversation in a project"}
		>
			<button
				type="button"
				aria-label={label}
				onClick={onMove}
				className={headerIconButtonClass()}
			>
				<FolderInput className="size-3.5" />
			</button>
		</HeaderTip>
	);
}

const MobileActionsCloseContext = createContext<() => void>(() => {});

export function ChatMobileProjectRow({ onMove }: { onMove: () => void }) {
	const close = useContext(MobileActionsCloseContext);
	const project = useChatHeaderStore((state) => state.project);
	return (
		<section className="mt-6">
			<div className="mb-2 px-1">
				<h2 className="font-display text-[15px] font-semibold text-sidebar-foreground">
					Project
				</h2>
			</div>
			<div className="flex min-h-14 items-center justify-between gap-4 rounded-[12px] border border-sidebar-border bg-card px-4 py-2.5">
				{project ? (
					<Link
						href={project.href}
						onClick={close}
						className="flex min-w-0 items-center gap-2.5 text-[15px] font-semibold text-sidebar-foreground transition-colors hover:text-sidebar-active-icon"
					>
						<ProjectGlyph emoji={project.emoji} className="size-[18px]" />
						<span className="min-w-0">
							<span className="block truncate">{project.name}</span>
							{project.folderPath && (
								<span className="block truncate text-[13px] font-medium text-sidebar-muted">
									{project.folderPath}
								</span>
							)}
						</span>
					</Link>
				) : (
					<span className="flex min-w-0 items-center gap-2.5 text-[15px] font-semibold text-sidebar-muted">
						<Folder className="size-[18px] shrink-0" />
						No project
					</span>
				)}
				<button
					type="button"
					onClick={() => {
						close();
						onMove();
					}}
					className="flex h-10 shrink-0 touch-manipulation cursor-pointer items-center rounded-[8px] bg-petrol px-3.5 text-[14px] font-semibold text-white shadow-raised transition-[background-color,transform] hover:bg-petrol/90 active:scale-[0.98] dark:bg-white dark:text-ink dark:hover:bg-white/90"
				>
					Move
				</button>
			</div>
		</section>
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
	const closeMobileActions = useCallback(() => {
		setOpen(false);
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
				<div className="overflow-y-auto p-5">
					<ChatMobileModelCost />
					<MobileActionsCloseContext.Provider value={closeMobileActions}>
						{children}
					</MobileActionsCloseContext.Provider>
				</div>
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
			<HeaderTip
				label={enabled ? "Memories on" : "Memories off"}
				hint={
					enabled
						? "The agent can recall and save memories in this conversation"
						: "The agent neither recalls nor saves memories here"
				}
			>
				<button
					type="button"
					aria-label={label}
					aria-pressed={enabled}
					disabled={disabled || saving}
					onClick={() => {
						onChange(!enabled);
					}}
					className="flex h-full w-[30px] cursor-pointer items-center justify-center transition-colors hover:bg-black/5 hover:text-foreground disabled:cursor-default disabled:opacity-45 dark:hover:bg-white/5"
				>
					{saving ? (
						<LoaderCircle className="size-3.5 animate-spin" />
					) : (
						<Brain className="size-3.5" />
					)}
				</button>
			</HeaderTip>
			<HeaderTip label="Memory settings" hint="Review and manage what the agent remembers">
				<Link
					href="/settings?tab=profile&section=memories"
					aria-label="Open memory settings"
					className="flex h-full w-6 items-center justify-center border-l border-current/15 opacity-65 transition-colors hover:bg-black/5 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none dark:hover:bg-white/5"
				>
					<Settings2 className="size-3" />
				</Link>
			</HeaderTip>
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
			<HeaderTip label={enabled ? "Notifications on" : "Notifications off"} hint={label}>
				<button
					type="button"
					role="switch"
					aria-label="Notifications for this conversation"
					aria-checked={enabled}
					disabled={saving}
					onClick={() => {
						void setEnabled(!enabled);
					}}
					className="flex h-full w-[30px] cursor-pointer items-center justify-center transition-colors hover:bg-black/5 hover:text-foreground disabled:cursor-wait disabled:opacity-45 dark:hover:bg-white/5"
				>
					{saving ? (
						<LoaderCircle className="size-3.5 animate-spin" />
					) : enabled ? (
						<Bell className="size-3.5" />
					) : (
						<BellOff className="size-3.5" />
					)}
				</button>
			</HeaderTip>
			<HeaderTip label="Notification settings" hint="Default for new conversations">
				<Link
					href="/settings?tab=profile&section=preferences"
					aria-label="Default for new conversations"
					className="flex h-full w-6 items-center justify-center border-l border-current/15 opacity-65 transition-colors hover:bg-black/5 hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none dark:hover:bg-white/5"
				>
					<Settings2 className="size-3" />
				</Link>
			</HeaderTip>
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
				<ProjectCrumb />
				<div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-petrol-tint dark:bg-white/10">
					<AlarmClock className="size-3.5 text-petrol dark:text-panel-terminal" />
				</div>
				{triggerId ? (
					<Link
						href={`/triggers/${triggerId}`}
						className="min-w-0 cursor-pointer truncate rounded-sm font-semibold leading-none text-foreground transition-colors hover:text-petrol focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 dark:hover:text-panel-terminal"
					>
						{triggerName}
					</Link>
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
		return (
			<HeaderBar>
				<ProjectCrumb standalone />
			</HeaderBar>
		);
	}

	return (
		<HeaderBar>
			<ProjectCrumb />
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

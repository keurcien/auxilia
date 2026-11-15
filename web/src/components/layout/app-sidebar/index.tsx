"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
	AlarmClock,
	AlertCircle,
	Bot,
	Check,
	Circle,
	CircleCheck,
	CircleDashed,
	ChevronDown,
	ChevronRight,
	Loader2,
	Server,
	ScrollText,
	SquarePen,
	MoreVertical,
	Pencil,
	Trash2,
	LogOut,
	BookOpen,
	Settings,
	Users,
	Undo2,
	Moon,
	Sun,
	Monitor,
	List,
	UserRound,
	Info,
	FolderKanban,
	MessageSquare,
	MessagesSquare,
	FolderInput,
	Mail,
	MailOpen,
	type LucideIcon,
} from "lucide-react";
import {
	Sidebar,
	SidebarContent,
	SidebarFooter,
	SidebarGroup,
	SidebarGroupContent,
	SidebarGroupLabel,
	SidebarHeader,
	SidebarMenu,
	SidebarMenuButton,
	SidebarMenuItem,
	SidebarMenuAction,
	SidebarTrigger,
	useSidebar,
} from "@/components/ui/sidebar";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { TelegramLogo } from "@/components/telegram-logo";
import { WhatsAppLogo } from "@/components/whatsapp-logo";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { useAgentsStore } from "@/stores/agents-store";
import { useTriggersStore } from "@/stores/triggers-store";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useAppearanceStore } from "@/stores/appearance-store";
import { useProjectsStore } from "@/stores/projects-store";
import * as threadsApi from "@/lib/api/resources/threads";
import { appearanceLogoUrl } from "@/lib/api/resources/appearance";
import { useSkillsStore } from "@/stores/skills-store";
import { formatRunAt } from "@/lib/triggers/schedule";
import { useActiveRunThreadIds } from "@/hooks/use-active-runs";
import { useRowSelection } from "@/hooks/use-row-selection";
import { LONG_PRESS_TARGET_CLASS, useLongPress } from "@/hooks/use-long-press";
import { navigateWithUnsavedChanges } from "@/hooks/use-unsaved-changes-warning";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { UserAvatar } from "@/components/ui/user-avatar";
import {
	BulkConfirmDialog,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import { ThreadUnreadBadge } from "@/components/ui/thread-unread-badge";
import { RenameThreadDialog } from "@/components/layout/app-sidebar/rename-thread-dialog";
import { AboutDialog } from "@/components/layout/app-sidebar/about-dialog";
import { Thread } from "@/types/threads";
import { useTheme } from "next-themes";
import { WorkspaceSwitcher } from "@/components/layout/app-sidebar/workspace-switcher";
import { useShowShortcutsInMenu } from "@/lib/user-preferences";
import { getApiErrorMessage } from "@/lib/api/errors";
import { userRoleLabel } from "@/lib/user-role";
import { cn } from "@/lib/utils";
import {
	ProjectsTree,
	type ThreadCompletionFilter,
} from "@/components/layout/app-sidebar/projects-tree";
import {
	ThreadPlacementDialog,
	type ThreadPlacementTarget,
} from "@/components/layout/app-sidebar/thread-placement-dialog";
import { toast } from "sonner";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";

const navItems: {
	title: string;
	href: string;
	icon: LucideIcon;
	match?: "prefix";
}[] = [
	{
		title: "Agents",
		href: "/agents",
		icon: Bot,
	},
	{
		title: "Triggers",
		href: "/triggers",
		icon: AlarmClock,
		match: "prefix",
	},
	{
		title: "MCP Servers",
		href: "/mcp-servers",
		icon: Server,
	},
	{
		title: "Skills",
		href: "/skills",
		icon: ScrollText,
		match: "prefix",
	},
	{
		title: "Users",
		href: "/users",
		icon: Users,
	},
];

type ThemeMode = "system" | "dark" | "light";
const NEXT_THEME: Record<ThemeMode, ThemeMode> = {
	system: "dark",
	dark: "light",
	light: "system",
};

const THEME_LABELS: Record<ThemeMode, string> = {
	system: "System mode",
	dark: "Dark mode",
	light: "Light mode",
};

const NEXT_THREAD_FILTER: Record<
	ThreadCompletionFilter,
	ThreadCompletionFilter
> = {
	mixed: "uncompleted",
	uncompleted: "completed",
	completed: "mixed",
};

const THREAD_FILTER_COPY: Record<
	ThreadCompletionFilter,
	{ label: string; description: string }
> = {
	mixed: {
		label: "Mixed",
		description: "Showing open and completed conversations",
	},
	uncompleted: {
		label: "Uncompleted",
		description: "Showing open conversations only",
	},
	completed: {
		label: "Completed",
		description: "Showing completed conversations only",
	},
};

/** Compact relative time for thread rows: now, 5m, 2h, 3d, 4w */
function shortTimeAgo(dateStr: string): string {
	const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
	if (seconds < 60) return "now";
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h`;
	const days = Math.floor(hours / 24);
	if (days < 7) return `${days}d`;
	return `${Math.floor(days / 7)}w`;
}

function sortRecentThreads(
	threads: Thread[],
	activeRunThreadIds: Set<string>,
): Thread[] {
	return [...threads].sort((left, right) => {
		const leftPriority = activeRunThreadIds.has(left.id)
			? 0
			: left.isUnread
				? 1
				: 2;
		const rightPriority = activeRunThreadIds.has(right.id)
			? 0
			: right.isUnread
				? 1
				: 2;
		if (leftPriority !== rightPriority) {
			return leftPriority - rightPriority;
		}

		const leftActivityAt = new Date(
			left.updatedAt ?? left.createdAt,
		).getTime();
		const rightActivityAt = new Date(
			right.updatedAt ?? right.createdAt,
		).getTime();
		return rightActivityAt - leftActivityAt;
	});
}

/** 22px leading-icon slot — the fixed column that keeps icons anchored
 * at the same x position whether the sidebar is open or collapsed. */
function IconSlot({ children }: { children: React.ReactNode }) {
	return (
		<span className="flex w-[22px] shrink-0 items-center justify-center">
			{children}
		</span>
	);
}

function CycleFilterControl({
	name,
	copy,
	icon: Icon,
	active,
	onChange,
}: {
	name: string;
	copy: { label: string; description: string };
	icon: LucideIcon;
	active: boolean;
	onChange: () => void;
}) {
	return (
		<Tooltip>
			<TooltipTrigger asChild>
				<button
					type="button"
					onClick={onChange}
					aria-label={`${name}: ${copy.label}`}
					className={cn(
						"relative flex size-4 shrink-0 cursor-pointer items-center justify-center rounded-[4px] transition-colors after:absolute after:-inset-1.5 hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring",
						active ? "text-sidebar-active-icon" : "text-sidebar-muted",
					)}
				>
					<Icon className="size-3" />
				</button>
			</TooltipTrigger>
			<TooltipContent
				side="right"
				sideOffset={10}
				className="px-2.5 py-2 shadow-xl"
			>
				<div className="flex min-w-44 flex-col gap-0.5">
					<span className="font-semibold">{copy.label}</span>
					<span className="text-[10px] opacity-70">{copy.description}</span>
				</div>
			</TooltipContent>
		</Tooltip>
	);
}

const THREAD_FILTER_ICON: Record<ThreadCompletionFilter, LucideIcon> = {
	mixed: CircleDashed,
	uncompleted: Circle,
	completed: CircleCheck,
};

type ThreadSourceFilter = "all" | "conversations" | "triggers";

const NEXT_THREAD_SOURCE_FILTER: Record<ThreadSourceFilter, ThreadSourceFilter> =
	{
		all: "conversations",
		conversations: "triggers",
		triggers: "all",
	};

const THREAD_SOURCE_FILTER_COPY: Record<
	ThreadSourceFilter,
	{ label: string; description: string }
> = {
	all: {
		label: "All threads",
		description: "Showing conversations and trigger runs",
	},
	conversations: {
		label: "Conversations",
		description: "Showing conversations only",
	},
	triggers: {
		label: "Trigger runs",
		description: "Showing trigger runs only",
	},
};

const THREAD_SOURCE_FILTER_ICON: Record<ThreadSourceFilter, LucideIcon> = {
	all: MessagesSquare,
	conversations: MessageSquare,
	triggers: AlarmClock,
};

const THREAD_COMPLETION_FILTER_KEY = "auxilia:recent-threads-completion-filter";
const THREAD_SOURCE_FILTER_KEY = "auxilia:recent-threads-source-filter";

function parseThreadCompletionFilter(
	value: string | null,
): ThreadCompletionFilter | null {
	return value === "mixed" || value === "uncompleted" || value === "completed"
		? value
		: null;
}

function parseThreadSourceFilter(value: string | null): ThreadSourceFilter | null {
	return value === "all" || value === "conversations" || value === "triggers"
		? value
		: null;
}

export function AppSidebar() {
	const router = useRouter();
	const pathname = usePathname();
	const { agents, isInitialized: agentsReady } = useAgentsStore();
	const {
		threads,
		total,
		isLoadingMore,
		loadMoreThreads,
		removeThread,
		setThreadCompleted,
		setThreadReadState,
	} = useThreadsStore();
	const triggers = useTriggersStore((state) => state.triggers);
	const refreshProjectTree = useProjectsStore((state) => state.refreshTree);
	const triggersReady = useTriggersStore((state) => state.isInitialized);
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const mcpServersReady = useMcpServersStore((state) => state.isInitialized);
	const skills = useSkillsStore((state) => state.skills);
	const skillsReady = useSkillsStore((state) => state.isInitialized);
	const hasMoreThreads = threads.length < total;
	const { user, logout } = useUserStore();
	const canDeleteThreads = user?.canDeleteThreads === true;
	const { theme, setTheme } = useTheme();
	const themeMode: ThemeMode =
		theme === "dark" || theme === "light" ? theme : "system";
	const ThemeIcon =
		themeMode === "system" ? Monitor : themeMode === "dark" ? Moon : Sun;
	const { isMobile, setOpen, setOpenMobile, state: sidebarState } = useSidebar();
	const [renamingThread, setRenamingThread] = useState<Thread | null>(null);
	const [openThreadMenuId, setOpenThreadMenuId] = useState<string | null>(null);
	const [aboutOpen, setAboutOpen] = useState(false);
	const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
	const [sidebarMode, setSidebarMode] = useState<"threads" | "projects">(
		"threads",
	);
	const [threadCompletionFilter, setThreadCompletionFilter] =
		useState<ThreadCompletionFilter>("mixed");
	const [threadSourceFilter, setThreadSourceFilter] =
		useState<ThreadSourceFilter>("all");
	const [movingThread, setMovingThread] =
		useState<ThreadPlacementTarget | null>(null);
	const filteredThreads = threads.filter((thread) => {
		if (threadSourceFilter !== "all") {
			const isTriggerThread = thread.source === "trigger";
			if (isTriggerThread !== (threadSourceFilter === "triggers")) {
				return false;
			}
		}
		if (threadCompletionFilter === "mixed") return true;
		if (threadCompletionFilter === "completed") {
			return thread.completedAt != null;
		}
		return thread.completedAt == null;
	});
	const activeRunThreadIds = useActiveRunThreadIds(filteredThreads);
	const visibleThreads = sortRecentThreads(
		filteredThreads,
		activeRunThreadIds,
	);
	const appearance = useAppearanceStore((state) => state.appearance);
	const showShortcutsInMenu = useShowShortcutsInMenu();
	const threadLongPress = useLongPress();
	const selection = useRowSelection({
		orderedIds: visibleThreads.map((thread) => thread.id),
	});
	const selectedThreads = visibleThreads.filter((thread) =>
		selection.selectedIds.has(thread.id),
	);

	useEffect(() => {
		if (isMobile) setOpenMobile(false);
	}, [isMobile, pathname, setOpenMobile]);

	useEffect(() => {
		if (!canDeleteThreads && selection.selectionMode) selection.clear();
	}, [canDeleteThreads, selection]);

	useEffect(() => {
		const saved = window.localStorage.getItem("auxilia:sidebar-mode");
		if (saved !== "projects") return;
		queueMicrotask(() => {
			setSidebarMode("projects");
		});
	}, []);

	useEffect(() => {
		const saved = parseThreadCompletionFilter(
			window.localStorage.getItem(THREAD_COMPLETION_FILTER_KEY),
		);
		if (saved === null) return;
		queueMicrotask(() => {
			setThreadCompletionFilter(saved);
		});
	}, []);

	useEffect(() => {
		const saved = parseThreadSourceFilter(
			window.localStorage.getItem(THREAD_SOURCE_FILTER_KEY),
		);
		if (saved === null) return;
		queueMicrotask(() => {
			setThreadSourceFilter(saved);
		});
	}, []);

	const clearSelection = selection.clear;
	useEffect(() => {
		// Fired only in the other tabs, when one of them saves a filter.
		const handleStorage = (event: StorageEvent) => {
			if (event.key === THREAD_COMPLETION_FILTER_KEY) {
				const next = parseThreadCompletionFilter(event.newValue);
				if (next === null) return;
				clearSelection();
				setThreadCompletionFilter(next);
			} else if (event.key === THREAD_SOURCE_FILTER_KEY) {
				const next = parseThreadSourceFilter(event.newValue);
				if (next === null) return;
				clearSelection();
				setThreadSourceFilter(next);
			}
		};
		window.addEventListener("storage", handleStorage);
		return () => {
			window.removeEventListener("storage", handleStorage);
		};
	}, [clearSelection]);

	const changeSidebarMode = (mode: "threads" | "projects") => {
		if (mode === "projects") selection.clear();
		setSidebarMode(mode);
		window.localStorage.setItem("auxilia:sidebar-mode", mode);
	};

	const cycleThreadCompletionFilter = () => {
		const next = NEXT_THREAD_FILTER[threadCompletionFilter];
		selection.clear();
		setThreadCompletionFilter(next);
		window.localStorage.setItem(THREAD_COMPLETION_FILTER_KEY, next);
	};

	const cycleThreadSourceFilter = () => {
		const next = NEXT_THREAD_SOURCE_FILTER[threadSourceFilter];
		selection.clear();
		setThreadSourceFilter(next);
		window.localStorage.setItem(THREAD_SOURCE_FILTER_KEY, next);
	};

	const navCounts: Record<string, number | undefined> = {
		"/agents": agentsReady ? agents.length : undefined,
		"/triggers": triggersReady ? triggers.length : undefined,
		"/mcp-servers": mcpServersReady ? mcpServers.length : undefined,
		"/skills": skillsReady ? skills.length : undefined,
	};

	const handleDeleteThread = (threadId: string) => {
		if (!canDeleteThreads) return;
		threadsApi
			.deleteThread(threadId)
			.then(() => {
				removeThread(threadId);
			})
			.catch((error) => {
				console.error("Error deleting thread: ", error);
			});
	};

	const handleThreadCompletion = async (thread: Thread) => {
		try {
			await setThreadCompleted(thread.id, !thread.completedAt);
			void refreshProjectTree();
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation could not be updated."),
			);
		}
	};

	const handleThreadReadState = async (thread: Thread) => {
		try {
			await setThreadReadState(thread.id, !thread.isUnread);
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation could not be updated."),
			);
		}
	};

	const handleLogout = () => {
		void navigateWithUnsavedChanges(logout);
	};
	const navigateTo = (href: string) => {
		void navigateWithUnsavedChanges(() => {
			router.push(href);
		}).then((navigated) => {
			if (navigated && isMobile) setOpenMobile(false);
		});
	};
	return (
		<>
			<Sidebar collapsible="icon">
				{!isMobile && sidebarState === "collapsed" && (
					<button
						type="button"
						onClick={() => {
							setOpen(true);
						}}
						title="Expand sidebar"
						aria-label="Expand sidebar"
						className="absolute -right-3 top-3 z-30 flex size-6 cursor-pointer items-center justify-center rounded-full border border-sidebar-border bg-sidebar text-sidebar-muted shadow-raised transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
					>
						<ChevronRight className="size-3.5" strokeWidth={2.25} />
					</button>
				)}
				<SidebarHeader>
					<div className="flex h-9 items-center gap-2 pl-2 pr-1">
						<Link
							href="/"
							title="Home"
							aria-label="Home"
							className="group/brand relative size-[22px] shrink-0 cursor-pointer"
						>
							<span className="absolute inset-0 grid place-items-center rounded-md">
								{appearance.logoRevision ? (
									// Browser-direct request avoids routing a workspace image
									// through Next's optimizer.
									// eslint-disable-next-line @next/next/no-img-element
									<img
										src={appearanceLogoUrl(appearance.logoRevision)}
										alt={appearance.appName}
										className="size-[22px] rounded-[5px] object-cover"
									/>
								) : (
									<>
										<Image
											src="/logo.svg"
											alt={appearance.appName}
											height={22}
											width={22}
											className="dark:hidden"
										/>
										<Image
											src="/logo-dark.svg"
											alt={appearance.appName}
											height={22}
											width={22}
											className="hidden dark:block"
										/>
									</>
								)}
							</span>
						</Link>
						<Link
							href="/"
							className="cursor-pointer font-display text-[15.5px] font-bold tracking-[-0.02em] text-sidebar-foreground group-data-[collapsible=icon]:hidden animate-in fade-in duration-200"
							style={{ animationDelay: "100ms", animationFillMode: "both" }}
						>
							{appearance.appName}
						</Link>
						<SidebarTrigger className="ml-auto cursor-pointer text-sidebar-muted group-data-[collapsible=icon]:hidden" />
					</div>
					<WorkspaceSwitcher />
				</SidebarHeader>

				<SidebarContent>
					<SidebarGroup>
						<div className="flex items-center gap-1.5">
							<button
								onClick={() => {
									if (agents.length > 0) {
										const lastAgent = threads[0]
											? agents.find((a) => a.id === threads[0].agentId)
											: undefined;
										navigateTo(`/agents/${(lastAgent ?? agents[0]).id}/chat`);
									}
								}}
								disabled={agents.length === 0}
								title="New thread"
								className={`flex h-9 min-w-0 flex-1 cursor-pointer items-center gap-[9px] rounded-lg border border-input bg-card pl-2 pr-2.5 text-[13.5px] font-semibold text-sidebar-foreground shadow-raised transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50 group-data-[collapsible=icon]:w-[38px] group-data-[collapsible=icon]:flex-none group-data-[collapsible=icon]:px-1.75 ${
									selection.selectionMode
										? "group-data-[collapsible=icon]:hidden"
										: ""
								}`}
							>
								<IconSlot>
									<SquarePen className="size-4" />
								</IconSlot>
								<span className="truncate group-data-[collapsible=icon]:hidden">
									New thread
								</span>
							</button>
							{canDeleteThreads && selection.selectionMode && (
								<button
									type="button"
									title={`Delete ${selection.selectedCount} selected conversation${
										selection.selectedCount === 1 ? "" : "s"
									}`}
									aria-label={`Delete ${selection.selectedCount} selected conversation${
										selection.selectedCount === 1 ? "" : "s"
									}`}
									onClick={() => {
										setBulkDeleteOpen(true);
									}}
									className="relative flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-lg border border-destructive/20 bg-destructive/8 text-destructive shadow-raised transition-[background-color,border-color,transform] duration-150 hover:border-destructive/35 hover:bg-destructive/13 active:scale-[0.97] group-data-[collapsible=icon]:w-[38px] animate-in fade-in zoom-in-95"
								>
									<Trash2 className="size-4" />
									<span className="absolute -right-1 -top-1 flex min-w-4 items-center justify-center rounded-full bg-destructive px-1 font-mono text-[9px] font-semibold leading-4 text-white ring-2 ring-sidebar">
										{selection.selectedCount}
									</span>
								</button>
							)}
						</div>
					</SidebarGroup>

					<SidebarGroup className="pt-0 pb-1 group-data-[collapsible=icon]:hidden">
						<div className="grid grid-cols-2 rounded-[8px] border border-sidebar-border bg-sidebar-accent/45 p-0.5">
							{[
								{
									key: "threads" as const,
									label: "Threads",
									icon: MessagesSquare,
								},
								{
									key: "projects" as const,
									label: "Projects",
									icon: FolderKanban,
								},
							].map((item) => (
								<button
									key={item.key}
									type="button"
									aria-pressed={sidebarMode === item.key}
									onClick={() => {
										changeSidebarMode(item.key);
									}}
									className={cn(
										"flex h-7 cursor-pointer items-center justify-center gap-1.5 whitespace-nowrap rounded-[6px] text-[11.5px] font-semibold transition-colors",
										sidebarMode === item.key
											? "bg-card text-sidebar-foreground shadow-raised"
											: "text-sidebar-muted hover:text-sidebar-foreground",
									)}
								>
									<item.icon className="size-3.5" />
									{item.label}
								</button>
							))}
						</div>
					</SidebarGroup>

					<SidebarGroup className="flex-1 min-h-0 overflow-hidden pt-0">
						{sidebarMode === "threads" ? (
							<>
								{/* mt-0 cancels shadcn's collapsed -mt-8 and nowrap keeps the
						    (invisible) label the same height in the narrow rail, so the
						 thread rows below don't move when collapsing */}
								<SidebarGroupLabel className="h-auto overflow-hidden whitespace-nowrap pl-2 pr-[5px] pt-2 pb-1.5 font-sans text-[10px] font-semibold text-sidebar-muted-highlight group-data-[collapsible=icon]:mt-0">
									<span>Recent threads</span>
									<div className="ml-auto flex items-center gap-1">
										<CycleFilterControl
											name="Thread source filter"
											copy={THREAD_SOURCE_FILTER_COPY[threadSourceFilter]}
											icon={THREAD_SOURCE_FILTER_ICON[threadSourceFilter]}
											active={threadSourceFilter !== "all"}
											onChange={cycleThreadSourceFilter}
										/>
										<CycleFilterControl
											name="Thread filter"
											copy={THREAD_FILTER_COPY[threadCompletionFilter]}
											icon={THREAD_FILTER_ICON[threadCompletionFilter]}
											active={threadCompletionFilter !== "mixed"}
											onChange={cycleThreadCompletionFilter}
										/>
										<Link
											href="/settings?tab=profile&section=threads"
											title="View all threads"
											aria-label="View all threads"
											onClick={() => {
												if (isMobile) setOpenMobile(false);
											}}
											className="relative flex size-4 shrink-0 items-center justify-end rounded-[4px] text-sidebar-muted transition-colors after:absolute after:-inset-1.5 hover:text-sidebar-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
										>
											<List className="size-3" />
										</Link>
									</div>
								</SidebarGroupLabel>
								<SidebarGroupContent className="overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
									<SidebarMenu className="gap-px">
										{visibleThreads.map((thread, i) => {
											const isActive =
												pathname ===
												`/agents/${thread.agentId}/chat/${thread.id}`;
											const isTriggerThread = thread.source === "trigger";
											// Trigger threads are titled by firing time; the trigger
											// name (stored as first_message_content) becomes the
											// subtitle in place of the agent name.
											const title = isTriggerThread
												? formatRunAt(
														thread.createdAt,
														Intl.DateTimeFormat().resolvedOptions().timeZone,
													)
												: (thread.firstMessageContent ??
													"Untitled conversation");
											const subtitle = thread.agentArchived
												? "Archived agent"
												: isTriggerThread
													? thread.firstMessageContent
													: thread.agentName;
											const isMenuOpen = openThreadMenuId === thread.id;
											const trailingMetadataClass = !selection.selectionMode
												? isMenuOpen
													? "opacity-0 transition-opacity"
													: "opacity-0 transition-opacity md:opacity-100 md:group-hover/menu-item:opacity-0 md:group-focus-within/menu-item:opacity-0"
												: "";
											return (
												<SidebarMenuItem
													key={thread.id}
													className="animate-in fade-in duration-300"
													style={{
														animationDelay: `${Math.min(i, 10) * 30}ms`,
														animationFillMode: "both",
													}}
												>
													<SidebarMenuButton
														asChild
														isActive={isActive}
														tooltip={title}
														data-selected={
															selection.isSelected(thread.id) || undefined
														}
														className={`h-12 rounded-[7px] pr-[5px]! focus-visible:ring-inset hover:bg-sidebar-hover data-[active=true]:bg-sidebar-accent data-[selected=true]:bg-sidebar-accent group-data-[collapsible=icon]:h-12! group-data-[collapsible=icon]:w-[38px]! group-data-[collapsible=icon]:p-[5px]! group-data-[collapsible=icon]:data-[active=true]:bg-transparent group-data-[collapsible=icon]:data-[selected=true]:bg-sidebar-accent ${
															isMenuOpen ? "bg-sidebar-hover" : ""
														}`}
													>
														<Link
															href={`/agents/${thread.agentId}/chat/${thread.id}`}
															// Every visible link would otherwise fire two router
															// prefetches on page load — dozens of requests for
															// threads the user rarely opens.
															prefetch={false}
															{...threadLongPress.bind(
																canDeleteThreads
																	? () => {
																			if (!selection.isSelected(thread.id)) {
																				selection.toggle(thread.id);
																			}
																		}
																	: undefined,
															)}
															onClickCapture={threadLongPress.onClickCapture}
															onClick={(event) => {
																if (selection.selectionMode) {
																	event.preventDefault();
																	selection.toggle(thread.id, event.shiftKey);
																	return;
																}
																if (isMobile) setOpenMobile(false);
															}}
															className={cn(
																"flex items-center gap-1.5 px-[5px]",
																canDeleteThreads && LONG_PRESS_TARGET_CLASS,
															)}
														>
															<span className="w-7 shrink-0" aria-hidden />
															<div className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
																<div className="flex items-center gap-1.5">
																	<span
																		className={`truncate text-[13px] leading-[1.45] text-sidebar-foreground ${isActive ? "font-semibold" : "font-medium"}`}
																	>
																		{title}
																	</span>
																	{thread.isUnread && <ThreadUnreadBadge />}
																</div>
																<div className="flex items-center gap-1.5">
																	<span className="truncate text-[10.5px] text-sidebar-muted-highlight">
																		{subtitle}
																	</span>
																</div>
															</div>
															<div
																className={`flex min-w-8 shrink-0 flex-col items-end justify-center gap-1 group-data-[collapsible=icon]:hidden ${trailingMetadataClass}`}
															>
																<span className="font-mono text-[10px] text-sidebar-section-label">
																	{shortTimeAgo(thread.createdAt)}
																</span>
																<div className="flex items-center gap-[3px]">
																	{!activeRunThreadIds.has(thread.id) &&
																		(thread.lastRunStatus === "error" ||
																			thread.lastRunStatus === "timeout") && (
																			<AlertCircle
																				aria-label="Last run failed"
																				className="size-3 shrink-0 text-destructive"
																			>
																				<title>Last run failed</title>
																			</AlertCircle>
																		)}
																	{thread.source === "slack" && (
																		<Image
																			src="https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/slack.png"
																			alt="Slack"
																			height={12}
																			width={12}
																			className="size-3 shrink-0"
																			title="Thread initiated in Slack"
																		/>
																	)}
																	{thread.source === "telegram" && (
																		<TelegramLogo className="size-3 shrink-0" />
																	)}
																	{thread.source === "whatsapp" && (
																		<WhatsAppLogo className="size-3 shrink-0" />
																	)}
																	{activeRunThreadIds.has(thread.id) ? (
																		<Loader2
																			aria-label="Running"
																			className="size-3 shrink-0 animate-spin text-sidebar-active-icon"
																		/>
																	) : (
																		<span
																			aria-label={
																				thread.completedAt
																					? "Conversation completed"
																					: "Conversation open"
																			}
																			title={
																				thread.completedAt
																					? "Completed"
																					: "Open"
																			}
																			className={cn(
																				"flex size-3 items-center justify-center rounded-full border",
																				thread.completedAt
																					? "border-emerald-600 bg-emerald-600 text-white"
																					: "border-sidebar-muted-highlight text-transparent",
																			)}
																		>
																			<Check
																				className="size-2"
																				strokeWidth={3}
																			/>
																		</span>
																	)}
																</div>
															</div>
														</Link>
													</SidebarMenuButton>
													<SelectableLeading
														selected={selection.isSelected(thread.id)}
														selectionMode={selection.selectionMode}
														disabled={!canDeleteThreads}
														label={`Select ${title}`}
														onToggle={(shiftKey) => {
															selection.toggle(thread.id, shiftKey);
														}}
														hoverOnSelf
														className="absolute left-[5px] top-1/2 z-10 size-7 -translate-y-1/2"
													>
														{isTriggerThread ? (
															<span
																title="Started by a trigger"
																className={`flex size-7 items-center justify-center rounded-[7px] border border-input bg-sidebar-accent ${
																	isActive
																		? "group-data-[collapsible=icon]:ring-2 group-data-[collapsible=icon]:ring-sidebar-ring"
																		: ""
																}`}
															>
																<AlarmClock className="size-3.5 text-sidebar-active-icon" />
															</span>
														) : (
															<AgentAvatar
																agentId={thread.agentId}
																name={thread.agentName}
																imageRevision={thread.agentImageRevision}
																color={thread.agentColor}
																emoji={thread.agentEmoji}
																size="xs"
																className={
																	isActive
																		? "group-data-[collapsible=icon]:ring-2 group-data-[collapsible=icon]:ring-sidebar-ring"
																		: undefined
																}
															/>
														)}
													</SelectableLeading>
													{!selection.selectionMode && (
														<DropdownMenu
															onOpenChange={(open) => {
																setOpenThreadMenuId((current) =>
																	open
																		? thread.id
																		: current === thread.id
																			? null
																			: current,
																);
															}}
															trigger={
																<SidebarMenuAction
																	showOnHover
																	className="z-20 cursor-pointer data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
																>
																	<MoreVertical className="size-4" />
																	<span className="sr-only">More options</span>
																</SidebarMenuAction>
															}
															side="right"
															align="start"
															items={[
																...(thread.completedAt == null
																	? [
																			{
																				label: thread.isUnread
																					? "Mark as read"
																					: "Mark as unread",
																				icon: thread.isUnread ? (
																					<MailOpen />
																				) : (
																					<Mail />
																				),
																				onClick: () => {
																					void handleThreadReadState(thread);
																				},
																			},
																		]
																	: []),
																{
																	label:
																		thread.completedAt == null
																			? "Mark as complete"
																			: "Reopen",
																	icon:
																		thread.completedAt == null ? (
																			<CircleCheck />
																		) : (
																			<Undo2 />
																		),
																	onClick: () => {
																		void handleThreadCompletion(thread);
																	},
																},
																{
																	label: "Move conversation",
																	icon: <FolderInput />,
																	onClick: () => {
																		setMovingThread({
																			id: thread.id,
																			title,
																			projectId: thread.projectId ?? null,
																			folderId: thread.folderId ?? null,
																		});
																	},
																},
																{
																	label: "Rename",
																	icon: <Pencil />,
																	onClick: () => {
																		setRenamingThread(thread);
																	},
																},
																...(canDeleteThreads
																	? [
																			{
																				label: "Delete",
																				icon: <Trash2 />,
																				destructive: true,
																				onClick: () => {
																					handleDeleteThread(thread.id);
																				},
																			},
																		]
																	: []),
															]}
														/>
													)}
												</SidebarMenuItem>
											);
										})}
										{hasMoreThreads && (
											<SidebarMenuItem className="group-data-[collapsible=icon]:hidden">
												<button
													type="button"
													disabled={isLoadingMore}
													onClick={() => {
														void loadMoreThreads();
													}}
													className="mt-1 flex h-8 w-full cursor-pointer items-center justify-center gap-2 rounded-[7px] text-[10.5px] text-sidebar-muted-highlight transition-colors hover:bg-sidebar-hover hover:text-sidebar-foreground disabled:cursor-default disabled:opacity-60"
												>
													{isLoadingMore ? (
														<Loader2 className="size-3.5 animate-spin" />
													) : (
														<ChevronDown className="size-3.5" />
													)}
													{isLoadingMore ? "loading…" : "show more"}
												</button>
											</SidebarMenuItem>
										)}
									</SidebarMenu>
								</SidebarGroupContent>
							</>
						) : (
							<>
								<SidebarGroupLabel className="h-auto overflow-hidden whitespace-nowrap pl-2 pr-[5px] pt-2 pb-1.5 font-sans text-[10px] font-semibold text-sidebar-muted-highlight group-data-[collapsible=icon]:mt-0">
									<span>Projects</span>
									<div className="ml-auto flex items-center">
										<CycleFilterControl
											name="Thread filter"
											copy={THREAD_FILTER_COPY[threadCompletionFilter]}
											icon={THREAD_FILTER_ICON[threadCompletionFilter]}
											active={threadCompletionFilter !== "mixed"}
											onChange={cycleThreadCompletionFilter}
										/>
									</div>
								</SidebarGroupLabel>
								<SidebarGroupContent className="overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
									<ProjectsTree
										pathname={pathname}
										completionFilter={threadCompletionFilter}
										closeMobile={() => {
											if (isMobile) setOpenMobile(false);
										}}
									/>
								</SidebarGroupContent>
							</>
						)}
					</SidebarGroup>

					<SidebarGroup
						className={`mt-auto hidden ${showShortcutsInMenu ? "md:flex" : ""}`}
					>
						<SidebarGroupLabel className="h-auto overflow-hidden whitespace-nowrap px-2 pt-2 pb-1.5 font-sans text-[10px] font-semibold text-sidebar-muted-highlight group-data-[collapsible=icon]:mt-0">
							Workspace
						</SidebarGroupLabel>
						<SidebarGroupContent>
							<SidebarMenu className="gap-px">
								{navItems.map((item) => {
									const isNavActive =
										item.match === "prefix"
											? pathname.startsWith(item.href)
											: pathname === item.href;
									const count = navCounts[item.href];
									return (
										<SidebarMenuItem key={item.href}>
											<SidebarMenuButton
												asChild
												isActive={isNavActive}
												tooltip={item.title}
												className="rounded-[7px] px-2 hover:bg-sidebar-hover data-[active=true]:bg-sidebar-accent group-data-[collapsible=icon]:w-[38px]! group-data-[collapsible=icon]:p-2!"
											>
												<Link
													href={item.href}
													className="flex items-center gap-[9px]"
												>
													<IconSlot>
														<item.icon
															className={
																isNavActive
																	? "text-sidebar-active-icon"
																	: "text-sidebar-muted"
															}
															size={16}
														/>
													</IconSlot>
													<span
														className={`truncate text-[13.5px] group-data-[collapsible=icon]:hidden ${isNavActive ? "font-semibold text-sidebar-foreground" : "font-medium text-sidebar-muted"}`}
													>
														{item.title}
													</span>
													{count !== undefined && (
														<span
															className={`ml-auto font-mono text-[10.5px] group-data-[collapsible=icon]:hidden ${isNavActive ? "text-sidebar-active-icon" : "text-sidebar-muted-highlight"}`}
														>
															{count}
														</span>
													)}
												</Link>
											</SidebarMenuButton>
										</SidebarMenuItem>
									);
								})}
							</SidebarMenu>
						</SidebarGroupContent>
					</SidebarGroup>
				</SidebarContent>

				<SidebarFooter className="border-t border-sidebar-border">
					<SidebarMenu>
						<SidebarMenuItem>
							<DropdownMenu
								modal={!isMobile}
								trigger={
									<SidebarMenuButton
										size="lg"
										tooltip={user?.name || "User"}
										// Collapsed, the avatar is the button's only visible
										// content and the name column is hidden — without this
										// the trigger has no accessible name (the tooltip is
										// aria-describedby, and the initials chip disappears
										// the moment the profile picture loads).
										aria-label={user?.name || "User"}
										className="h-11 cursor-pointer rounded-lg pl-[5px] pr-2 hover:bg-sidebar-hover data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground group-data-[collapsible=icon]:h-11! group-data-[collapsible=icon]:w-[38px]! group-data-[collapsible=icon]:p-0! group-data-[collapsible=icon]:pl-[5px]!"
									>
										<UserAvatar
											name={user?.name}
											pictureUrl={user?.pictureUrl}
											userId={user?.id}
											imageRevision={user?.imageRevision}
											className="size-7 shrink-0"
											fallbackClassName="bg-primary text-[10px] text-primary-foreground dark:bg-primary"
										/>
										<div className="grid flex-1 text-left leading-tight min-w-0 group-data-[collapsible=icon]:hidden">
											<span className="truncate text-[12.5px] font-semibold text-sidebar-foreground">
												{user?.name || "User"}
											</span>
											<span className="truncate text-[10px] text-sidebar-muted-highlight">
												{user ? userRoleLabel(user) : ""}
											</span>
										</div>
										<MoreVertical className="ml-auto size-4 shrink-0 text-sidebar-muted-highlight group-data-[collapsible=icon]:hidden" />
									</SidebarMenuButton>
								}
								side="top"
								align="end"
								sideOffset={4}
								className="max-h-[70dvh] w-(--radix-dropdown-menu-trigger-width) min-w-56 overflow-y-auto overscroll-contain"
								items={[
									{
										label: "Profile",
										icon: <UserRound />,
										onClick: () => {
											navigateTo("/settings?tab=profile");
										},
									},
									{
										label: "Settings",
										icon: <Settings />,
										onClick: () => {
											navigateTo("/settings");
										},
									},
									{
										label: "Documentation",
										icon: <BookOpen />,
										onClick: () =>
											window.open("https://auxilia-docs.vercel.app/", "_blank"),
									},
									{
										label: THEME_LABELS[themeMode],
										icon: <ThemeIcon />,
										onClick: () => {
											setTheme(NEXT_THEME[themeMode]);
										},
									},
									{
										label: "About",
										icon: <Info />,
										onClick: () => {
											setAboutOpen(true);
										},
									},
									...(isMobile || !showShortcutsInMenu
										? [
												{ separator: true as const },
												{ sectionLabel: "Workspace" },
												...navItems.map((item) => ({
													label: item.title,
													icon: <item.icon />,
													active:
														item.match === "prefix"
															? pathname.startsWith(item.href)
															: pathname === item.href,
													onClick: () => {
														navigateTo(item.href);
													},
												})),
											]
										: []),
									{ separator: true },
									{
										label: "Log out",
										icon: <LogOut />,
										destructive: true,
										onClick: handleLogout,
									},
								]}
							/>
						</SidebarMenuItem>
					</SidebarMenu>
				</SidebarFooter>
			</Sidebar>
			<RenameThreadDialog
				thread={renamingThread}
				onOpenChange={(open) => {
					if (!open) setRenamingThread(null);
				}}
			/>
			<BulkConfirmDialog
				open={bulkDeleteOpen}
				onOpenChange={setBulkDeleteOpen}
				title="Delete selected conversations?"
				description="Their messages and run history will be removed permanently. This cannot be undone."
				items={selectedThreads.map((thread) => ({
					id: thread.id,
					name: thread.firstMessageContent?.trim() || "Untitled conversation",
					note: thread.agentName ? `Agent: ${thread.agentName}` : undefined,
				}))}
				confirmLabel="Delete"
				busyLabel="Deleting…"
				onConfirm={async (items) => {
					const results = await Promise.allSettled(
						items.map((item) => threadsApi.deleteThread(item.id)),
					);
					const succeeded: string[] = [];
					const failures: BulkFailure[] = [];
					results.forEach((result, index) => {
						const item = items.at(index);
						if (!item) return;
						if (result.status === "fulfilled") {
							succeeded.push(item.id);
							removeThread(item.id);
						} else {
							failures.push({
								id: item.id,
								name: item.name,
								message: getApiErrorMessage(result.reason, "Delete failed."),
							});
						}
					});
					selection.remove(succeeded);
					return failures;
				}}
			/>
			<ThreadPlacementDialog
				open={movingThread !== null}
				onOpenChange={(open) => {
					if (!open) setMovingThread(null);
				}}
				thread={movingThread}
			/>
			<AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} />
		</>
	);
}

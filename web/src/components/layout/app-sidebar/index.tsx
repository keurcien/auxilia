"use client";

import { useState } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
	AlarmClock,
	AlertCircle,
	Bot,
	ChevronDown,
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
	Moon,
	Sun,
	PanelLeftOpen,
	UserRound,
	Info,
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
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { useAgentsStore } from "@/stores/agents-store";
import { useTriggersStore } from "@/stores/triggers-store";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useAppearanceStore } from "@/stores/appearance-store";
import * as threadsApi from "@/lib/api/resources/threads";
import { appearanceLogoUrl } from "@/lib/api/resources/appearance";
import { useSkillsStore } from "@/stores/skills-store";
import { formatRunAt } from "@/lib/triggers/schedule";
import { useActiveRunThreadIds } from "@/hooks/use-active-runs";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { UserAvatar } from "@/components/ui/user-avatar";
import { RenameThreadDialog } from "@/components/layout/app-sidebar/rename-thread-dialog";
import { AboutDialog } from "@/components/layout/app-sidebar/about-dialog";
import { Thread } from "@/types/threads";
import { useTheme } from "next-themes";
import { WorkspaceSwitcher } from "@/components/layout/app-sidebar/workspace-switcher";

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

/** 22px leading-icon slot — the fixed column that keeps icons anchored
 * at the same x position whether the sidebar is open or collapsed. */
function IconSlot({ children }: { children: React.ReactNode }) {
	return (
		<span className="flex w-[22px] shrink-0 items-center justify-center">
			{children}
		</span>
	);
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
	} = useThreadsStore();
	const triggers = useTriggersStore((state) => state.triggers);
	const triggersReady = useTriggersStore((state) => state.isInitialized);
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const mcpServersReady = useMcpServersStore((state) => state.isInitialized);
	const skills = useSkillsStore((state) => state.skills);
	const skillsReady = useSkillsStore((state) => state.isInitialized);
	const hasMoreThreads = threads.length < total;
	const { user, logout } = useUserStore();
	const { resolvedTheme, setTheme } = useTheme();
	const { toggleSidebar } = useSidebar();
	const [renamingThread, setRenamingThread] = useState<Thread | null>(null);
	const [aboutOpen, setAboutOpen] = useState(false);
	const activeRunThreadIds = useActiveRunThreadIds(threads);
	const appearance = useAppearanceStore((state) => state.appearance);

	const navCounts: Record<string, number | undefined> = {
		"/agents": agentsReady ? agents.length : undefined,
		"/triggers": triggersReady ? triggers.length : undefined,
		"/mcp-servers": mcpServersReady ? mcpServers.length : undefined,
		"/skills": skillsReady ? skills.length : undefined,
	};

	const handleDeleteThread = (threadId: string) => {
		threadsApi
			.deleteThread(threadId)
			.then(() => {
				removeThread(threadId);
			})
			.catch((error) => {
				console.error("Error deleting thread: ", error);
			});
	};

	const handleLogout = () => {
		logout();
	};
	return (
		<>
			<Sidebar collapsible="icon">
				<SidebarHeader>
					<div className="flex h-9 items-center gap-2 pl-2 pr-1">
						<button
							onClick={toggleSidebar}
							title="Toggle sidebar"
							aria-label="Toggle sidebar"
							className="group/brand relative size-[22px] shrink-0 cursor-pointer"
						>
							{/* Logo at rest; fades out on hover only when collapsed. */}
							<span className="absolute inset-0 grid place-items-center rounded-md transition-opacity duration-[140ms] group-data-[collapsible=icon]:group-hover/brand:opacity-0">
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
							{/* Expand glyph; revealed on hover only when collapsed. */}
							<span className="absolute inset-0 grid place-items-center rounded-md bg-sidebar-accent text-sidebar-active-icon opacity-0 transition-opacity duration-[140ms] group-data-[collapsible=icon]:group-hover/brand:opacity-100">
								<PanelLeftOpen className="size-4" />
							</span>
						</button>
						<span
							className="font-display text-[15.5px] font-bold tracking-[-0.02em] text-sidebar-foreground group-data-[collapsible=icon]:hidden animate-in fade-in duration-200"
							style={{ animationDelay: "100ms", animationFillMode: "both" }}
						>
							{appearance.appName}
						</span>
						<SidebarTrigger className="ml-auto cursor-pointer text-sidebar-muted group-data-[collapsible=icon]:hidden" />
					</div>
					<WorkspaceSwitcher />
				</SidebarHeader>

				<SidebarContent>
					<SidebarGroup>
						<button
							onClick={() => {
								if (agents.length > 0) {
									const lastAgent = threads[0]
										? agents.find((a) => a.id === threads[0].agentId)
										: undefined;
									router.push(`/agents/${(lastAgent ?? agents[0]).id}/chat`);
								}
							}}
							disabled={agents.length === 0}
							title="New thread"
							className="flex h-9 w-full cursor-pointer items-center gap-[9px] rounded-lg border border-input bg-card pl-2 pr-2.5 text-[13.5px] font-semibold text-sidebar-foreground shadow-raised transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50 group-data-[collapsible=icon]:w-[38px] group-data-[collapsible=icon]:px-1.75"
						>
							<IconSlot>
								<SquarePen className="size-4" />
							</IconSlot>
							<span className="group-data-[collapsible=icon]:hidden">
								New thread
							</span>
						</button>
					</SidebarGroup>

					<SidebarGroup className="flex-1 min-h-0 overflow-hidden pt-0">
						{/* mt-0 cancels shadcn's collapsed -mt-8 and nowrap keeps the
						    (invisible) label the same height in the narrow rail, so the
						 thread rows below don't move when collapsing */}
						<SidebarGroupLabel className="h-auto overflow-hidden whitespace-nowrap px-2 pt-2 pb-1.5 font-sans text-[10px] font-semibold text-sidebar-muted-highlight group-data-[collapsible=icon]:mt-0">
							Recent threads
						</SidebarGroupLabel>
						<SidebarGroupContent className="overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							<SidebarMenu className="gap-px">
								{threads.map((thread, i) => {
									const isActive =
										pathname === `/agents/${thread.agentId}/chat/${thread.id}`;
									const isTriggerThread = thread.source === "trigger";
									// Trigger threads are titled by firing time; the trigger
									// name (stored as first_message_content) becomes the
									// subtitle in place of the agent name.
									const title = isTriggerThread
										? formatRunAt(
												thread.createdAt,
												Intl.DateTimeFormat().resolvedOptions().timeZone,
											)
										: (thread.firstMessageContent ?? "Untitled conversation");
									const subtitle = thread.agentArchived
										? "Archived agent"
										: isTriggerThread
											? thread.firstMessageContent
											: thread.agentName;
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
												className="h-12 rounded-[7px] hover:bg-sidebar-hover data-[active=true]:bg-sidebar-accent group-data-[collapsible=icon]:h-12! group-data-[collapsible=icon]:w-[38px]! group-data-[collapsible=icon]:p-[5px]! group-data-[collapsible=icon]:data-[active=true]:bg-transparent"
											>
												<Link
													href={`/agents/${thread.agentId}/chat/${thread.id}`}
													// Every visible link would otherwise fire two router
													// prefetches on page load — dozens of requests for
													// threads the user rarely opens.
													prefetch={false}
													className="flex items-center gap-1.5 px-[5px]"
												>
													<span className="flex w-7 shrink-0 items-center justify-center">
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
													</span>
													<div className="min-w-0 flex-1 group-data-[collapsible=icon]:hidden">
														<div className="flex items-center gap-2">
															<span
																className={`truncate text-[13px] leading-[1.45] text-sidebar-foreground ${isActive ? "font-semibold" : "font-medium"}`}
															>
																{title}
															</span>
															<span className="ml-auto shrink-0 font-mono text-[10px] text-sidebar-section-label">
																{shortTimeAgo(thread.createdAt)}
															</span>
														</div>
														<div className="flex items-center gap-1.5">
															<span className="truncate text-[10.5px] text-sidebar-muted-highlight">
																{subtitle}
															</span>
															{activeRunThreadIds.has(thread.id) ? (
																<Loader2
																	aria-label="Running"
																	className="ml-auto size-3 shrink-0 animate-spin text-sidebar-active-icon"
																/>
															) : (
																(thread.lastRunStatus === "error" ||
																	thread.lastRunStatus === "timeout") && (
																	<AlertCircle
																		aria-label="Last run failed"
																		className="ml-auto size-3 shrink-0 text-destructive"
																	>
																		<title>Last run failed</title>
																	</AlertCircle>
																)
															)}
															{thread.source === "slack" && (
																<Image
																	src="https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/slack.png"
																	alt="Slack"
																	height={12}
																	width={12}
																	className={`size-3 shrink-0 ${activeRunThreadIds.has(thread.id) ? "" : "ml-auto"}`}
																	title="Thread initiated in Slack"
																/>
															)}
														</div>
													</div>
												</Link>
											</SidebarMenuButton>
											<DropdownMenu
												trigger={
													<SidebarMenuAction
														showOnHover
														className="cursor-pointer"
													>
														<MoreVertical className="size-4" />
														<span className="sr-only">More options</span>
													</SidebarMenuAction>
												}
												side="right"
												align="start"
												items={[
													{
														label: "Rename",
														icon: <Pencil />,
														onClick: () => {
															setRenamingThread(thread);
														},
													},
													{
														label: "Delete",
														icon: <Trash2 />,
														destructive: true,
														onClick: () => {
															handleDeleteThread(thread.id);
														},
													},
												]}
											/>
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
					</SidebarGroup>

					<SidebarGroup className="mt-auto">
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
												{user?.role || ""}
											</span>
										</div>
										<MoreVertical className="ml-auto size-4 shrink-0 text-sidebar-muted-highlight group-data-[collapsible=icon]:hidden" />
									</SidebarMenuButton>
								}
								side="top"
								align="end"
								sideOffset={4}
								className="w-(--radix-dropdown-menu-trigger-width) min-w-56"
								items={[
									{
										label: "Profile",
										icon: <UserRound />,
										onClick: () => {
											router.push("/settings?tab=profile");
										},
									},
									{
										label: "Settings",
										icon: <Settings />,
										onClick: () => {
											router.push("/settings");
										},
									},
									{
										label: "Documentation",
										icon: <BookOpen />,
										onClick: () =>
											window.open("https://auxilia-docs.vercel.app/", "_blank"),
									},
									{
										label:
											resolvedTheme === "dark" ? "Light mode" : "Dark mode",
										icon: resolvedTheme === "dark" ? <Sun /> : <Moon />,
										onClick: () => {
											setTheme(resolvedTheme === "dark" ? "light" : "dark");
										},
									},
									{
										label: "About",
										icon: <Info />,
										onClick: () => {
											setAboutOpen(true);
										},
									},
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
			<AboutDialog open={aboutOpen} onOpenChange={setAboutOpen} />
		</>
	);
}

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
	ChevronDown,
	Loader2,
	Server,
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
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { useAgentsStore } from "@/stores/agents-store";
import { api } from "@/lib/api/client";
import { formatRunAt } from "@/lib/triggers/schedule";
import { useActiveRunThreadIds } from "@/hooks/use-active-runs";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { RenameThreadDialog } from "@/components/layout/app-sidebar/rename-thread-dialog";
import { Thread } from "@/types/threads";
import { useTheme } from "next-themes";

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
		title: "Users",
		href: "/users",
		icon: Users,
	},
];

function getInitials(name: string | undefined): string {
	if (!name) return "U";
	const parts = name.trim().split(" ");
	if (parts.length >= 2) {
		return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
	}
	return name.substring(0, 2).toUpperCase();
}

export function AppSidebar() {
	const router = useRouter();
	const pathname = usePathname();
	const { agents, fetchAgents } = useAgentsStore();
	const {
		threads,
		total,
		isLoadingMore,
		fetchThreads,
		loadMoreThreads,
		removeThread,
	} = useThreadsStore();
	const hasMoreThreads = threads.length < total;
	const { user, fetchUser, logout } = useUserStore();
	const { resolvedTheme, setTheme } = useTheme();
	const { toggleSidebar } = useSidebar();
	const [renamingThread, setRenamingThread] = useState<Thread | null>(null);
	const activeRunThreadIds = useActiveRunThreadIds(threads);

	useEffect(() => {
		fetchUser();
		fetchThreads();
		fetchAgents();
	}, [fetchUser, fetchThreads, fetchAgents]);

	const handleDeleteThread = (threadId: string) => {
		api
			.delete(`/threads/${threadId}`)
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
			<Sidebar variant="floating" collapsible="icon">
				<SidebarHeader>
					<div className="flex h-10 items-center gap-2 px-2">
						<button
							onClick={toggleSidebar}
							title="Toggle sidebar"
							aria-label="Toggle sidebar"
							className="group/brand relative size-[26px] shrink-0 cursor-pointer"
						>
							{/* Logo at rest; fades out on hover only when collapsed. */}
							<span className="absolute inset-0 grid place-items-center rounded-md transition-opacity duration-[140ms] group-data-[collapsible=icon]:group-hover/brand:opacity-0">
								<Image
									src="/logo.svg"
									alt="auxilia"
									height={24}
									width={24}
									className="dark:hidden"
								/>
								<Image
									src="/logo-dark.svg"
									alt="auxilia"
									height={24}
									width={24}
									className="hidden dark:block"
								/>
							</span>
							{/* Expand glyph; revealed on hover only when collapsed. */}
							<span className="absolute inset-0 grid place-items-center rounded-md bg-sidebar-accent text-sidebar-active-icon opacity-0 transition-opacity duration-[140ms] group-data-[collapsible=icon]:group-hover/brand:opacity-100">
								<PanelLeftOpen className="size-4" />
							</span>
						</button>
						<span
							className="font-sans text-base font-semibold group-data-[collapsible=icon]:hidden animate-in fade-in duration-200"
							style={{ animationDelay: "100ms", animationFillMode: "both" }}
						>
							auxilia
						</span>
						<SidebarTrigger className="ml-auto cursor-pointer group-data-[collapsible=icon]:hidden" />
					</div>
				</SidebarHeader>

				<SidebarContent>
					<SidebarGroup>
						<div className="px-1">
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
								className="w-full h-8 px-2 rounded-xl border-none bg-[#111111] dark:bg-white text-[13.5px] font-semibold font-(family-name:--font-dm-sans) text-white dark:text-[#111111] flex items-center justify-start gap-4 cursor-pointer hover:opacity-90 transition-all shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] disabled:opacity-50 disabled:cursor-not-allowed"
							>
								<SquarePen className="size-4 shrink-0" />
								<span className="group-data-[collapsible=icon]:hidden">
									New thread
								</span>
							</button>
						</div>
					</SidebarGroup>

					<SidebarGroup className="flex-1 min-h-0 overflow-hidden">
						<SidebarGroupContent className="overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							<SidebarMenu>
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
										: thread.firstMessageContent;
									const subtitle = thread.agentArchived
										? "Archived agent"
										: isTriggerThread
											? thread.firstMessageContent
											: thread.agentName;
									return (
										<SidebarMenuItem
											key={thread.id}
											className="animate-in fade-in slide-in-from-bottom-3 duration-400"
											style={{
												animationDelay: `${Math.min(i, 10) * 50}ms`,
												animationFillMode: "both",
											}}
										>
											<SidebarMenuButton
												asChild
												isActive={isActive}
												tooltip={title}
												className="h-12! rounded-2xl transition-all duration-200 hover:translate-x-1 hover:bg-sidebar-hover data-[active=true]:bg-sidebar-accent group-data-[collapsible=icon]:h-12! group-data-[collapsible=icon]:w-full! group-data-[collapsible=icon]:p-0! group-data-[collapsible=icon]:hover:translate-x-0 group-data-[collapsible=icon]:data-[active=true]:bg-transparent"
											>
												<Link
													href={`/agents/${thread.agentId}/chat/${thread.id}`}
													className="h-full pl-[3px] pr-3 flex items-center gap-2.5 group-data-[collapsible=icon]:pl-[3px]!"
												>
													{thread.source === "trigger" ? (
														<div
															className={`flex items-center justify-center shrink-0 w-[34px] h-[34px] rounded-full border border-[#3D8B63]/15 bg-[#EDF4F0] dark:border-emerald-400/15 dark:bg-emerald-950/40 ${
																isActive
																	? "group-data-[collapsible=icon]:ring-2 group-data-[collapsible=icon]:ring-sidebar-primary"
																	: ""
															}`}
															title="Started by a trigger"
														>
															<AlarmClock className="size-4 text-[#3D8B63] dark:text-emerald-400" />
														</div>
													) : (
														<AgentAvatar
															color={thread.agentColor}
															emoji={thread.agentEmoji}
															size="sm"
															className={
																isActive
																	? "group-data-[collapsible=icon]:ring-2 group-data-[collapsible=icon]:ring-sidebar-primary"
																	: undefined
															}
														/>
													)}
													<div className="flex-1 min-w-0 text-left group-data-[collapsible=icon]:hidden">
														<div
															className={`font-[family-name:var(--font-dm-sans)] text-[14px] truncate leading-[1.45] ${isActive ? "font-semibold" : "font-medium"} text-sidebar-foreground`}
														>
															{title}
														</div>
														<div className="font-[family-name:var(--font-dm-sans)] text-[12px] text-[#999] dark:text-muted-foreground font-medium truncate mt-0.5 leading-snug">
															{subtitle}
														</div>
													</div>
													{activeRunThreadIds.has(thread.id) ? (
														<Loader2
															aria-label="Running"
															className="size-4 shrink-0 animate-spin text-[#4CA882] group-data-[collapsible=icon]:hidden"
														/>
													) : (
														(thread.lastRunStatus === "error" ||
															thread.lastRunStatus === "timeout") && (
															<AlertCircle
																aria-label="Last run failed"
																className="size-4 shrink-0 text-destructive group-data-[collapsible=icon]:hidden"
															>
																<title>Last run failed</title>
															</AlertCircle>
														)
													)}
													{thread.source === "slack" && (
														<Image
															src="https://storage.googleapis.com/choose-assets/slack.png"
															alt="Slack"
															height={16}
															width={16}
															className="h-4 w-4 shrink-0 group-data-[collapsible=icon]:hidden"
															title="Thread initiated in Slack"
														/>
													)}
												</Link>
											</SidebarMenuButton>
											<SageDropdownMenu
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
											className="mt-1 flex h-8 w-full cursor-pointer items-center justify-center gap-2 rounded-xl font-[family-name:var(--font-dm-sans)] text-[12.5px] font-medium text-sidebar-muted transition-colors hover:bg-sidebar-hover hover:text-sidebar-foreground disabled:cursor-default disabled:opacity-60"
										>
											{isLoadingMore ? (
												<Loader2 className="size-3.5 animate-spin" />
											) : (
												<ChevronDown className="size-3.5" />
											)}
											{isLoadingMore ? "Loading…" : "Show more"}
										</button>
									</SidebarMenuItem>
								)}
							</SidebarMenu>
						</SidebarGroupContent>
					</SidebarGroup>

					<SidebarGroup className="mt-auto">
						<SidebarGroupLabel className="font-[family-name:var(--font-dm-sans)] text-[10.5px] font-semibold uppercase tracking-[0.06em] text-sidebar-section-label group-data-[collapsible=icon]:mt-0">
							Workspace
						</SidebarGroupLabel>
						<SidebarGroupContent>
							<SidebarMenu>
								{navItems.map((item) => {
									const isNavActive =
										item.match === "prefix"
											? pathname.startsWith(item.href)
											: pathname === item.href;
									return (
										<SidebarMenuItem key={item.href}>
											<SidebarMenuButton
												asChild
												isActive={isNavActive}
												tooltip={item.title}
												className="rounded-[14px] pl-3 transition-all duration-200 hover:translate-x-0.5 hover:bg-sidebar-hover data-[active=true]:bg-sidebar-accent group-data-[collapsible=icon]:w-full! group-data-[collapsible=icon]:pl-3! group-data-[collapsible=icon]:hover:translate-x-0"
											>
												<Link href={item.href}>
													<item.icon
														className={
															isNavActive
																? "text-sidebar-active-icon"
																: "text-sidebar-muted"
														}
														size={17}
													/>
													<span
														className={`font-[family-name:var(--font-dm-sans)] text-[13.5px] group-data-[collapsible=icon]:hidden ${isNavActive ? "font-semibold text-sidebar-foreground" : "font-medium text-sidebar-muted"}`}
													>
														{item.title}
													</span>
												</Link>
											</SidebarMenuButton>
										</SidebarMenuItem>
									);
								})}
							</SidebarMenu>
						</SidebarGroupContent>
					</SidebarGroup>
				</SidebarContent>

				<SidebarFooter className="px-2 pb-3">
					<SidebarMenu>
						<SidebarMenuItem>
							<SageDropdownMenu
								trigger={
									<SidebarMenuButton
										size="lg"
										tooltip={user?.name || "User"}
										className="rounded-[18px] bg-sidebar-hover data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground cursor-pointer pl-0.5 pr-3 group-data-[collapsible=icon]:bg-transparent group-data-[collapsible=icon]:w-full! group-data-[collapsible=icon]:h-12! group-data-[collapsible=icon]:p-0! group-data-[collapsible=icon]:pl-0.5!"
									>
										<Avatar className="h-9 w-9 rounded-full">
											<AvatarFallback className="rounded-full bg-[#111111] dark:bg-white text-white dark:text-[#111111] text-xs font-bold">
												{getInitials(user?.name ?? undefined)}
											</AvatarFallback>
										</Avatar>
										<div className="grid flex-1 text-left leading-tight min-w-0 group-data-[collapsible=icon]:hidden">
											<span className="font-[family-name:var(--font-dm-sans)] truncate text-[13px] font-semibold text-sidebar-foreground">
												{user?.name || "User"}
											</span>
											<span className="font-[family-name:var(--font-dm-sans)] truncate text-[11px] text-sidebar-muted-highlight">
												{user?.email || ""}
											</span>
										</div>
									</SidebarMenuButton>
								}
								side="top"
								align="end"
								sideOffset={4}
								className="w-(--radix-dropdown-menu-trigger-width) min-w-56"
								items={[
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
		</>
	);
}

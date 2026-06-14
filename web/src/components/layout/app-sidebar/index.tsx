"use client";

import { useEffect } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
	Bot,
	Server,
	SquarePen,
	MoreVertical,
	Trash2,
	LogOut,
	BookOpen,
	Settings,
	Users,
	Moon,
	Sun,
	PanelLeftOpen,
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
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { useTheme } from "next-themes";

const navItems = [
	{
		title: "Agents",
		href: "/agents",
		icon: Bot,
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
	const { threads, fetchThreads, removeThread } = useThreadsStore();
	const { user, fetchUser, logout } = useUserStore();
	const { resolvedTheme, setTheme } = useTheme();
	const { toggleSidebar } = useSidebar();

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
					<div className="flex h-10 items-center gap-2 px-2 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0">
						<button
							onClick={toggleSidebar}
							title="Toggle sidebar"
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
						<span className="font-sans text-base font-semibold group-data-[collapsible=icon]:hidden">
							auxilia
						</span>
						<SidebarTrigger className="ml-auto cursor-pointer group-data-[collapsible=icon]:hidden" />
					</div>
				</SidebarHeader>

				<SidebarContent>
					<SidebarGroup>
						<div className="px-3 group-data-[collapsible=icon]:px-0">
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
								className="w-full h-10 px-4 rounded-full border-none bg-[#111111] dark:bg-white text-[13.5px] font-semibold font-(family-name:--font-dm-sans) text-white dark:text-[#111111] flex items-center justify-center gap-2 cursor-pointer hover:opacity-90 transition-all shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] disabled:opacity-50 disabled:cursor-not-allowed group-data-[collapsible=icon]:w-10 group-data-[collapsible=icon]:p-0 group-data-[collapsible=icon]:mx-auto"
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
									return (
										<SidebarMenuItem
											key={thread.id}
											className="animate-in fade-in slide-in-from-bottom-3 duration-400"
											style={{ animationDelay: `${i * 50}ms`, animationFillMode: "both" }}
										>
											<SidebarMenuButton
												asChild
												isActive={isActive}
												tooltip={thread.firstMessageContent}
												className="h-12! rounded-2xl transition-all duration-200 hover:translate-x-1 hover:bg-sidebar-hover data-[active=true]:bg-sidebar-accent group-data-[collapsible=icon]:w-10! group-data-[collapsible=icon]:p-0! group-data-[collapsible=icon]:mx-auto group-data-[collapsible=icon]:hover:translate-x-0 group-data-[collapsible=icon]:data-[active=true]:bg-transparent"
											>
												<Link
													href={`/agents/${thread.agentId}/chat/${thread.id}`}
													className="h-full px-3 flex items-center gap-2.5 group-data-[collapsible=icon]:px-0 group-data-[collapsible=icon]:justify-center"
												>
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
													<div className="flex-1 min-w-0 text-left group-data-[collapsible=icon]:hidden">
														<div
															className={`font-[family-name:var(--font-dm-sans)] text-[14px] truncate leading-[1.45] ${isActive ? "font-semibold" : "font-medium"} text-sidebar-foreground`}
														>
															{thread.firstMessageContent}
														</div>
														<div className="font-[family-name:var(--font-dm-sans)] text-[12px] text-[#999] dark:text-muted-foreground font-medium truncate mt-0.5 leading-snug">
															{thread.agentArchived
																? "Archived agent"
																: thread.agentName}
														</div>
													</div>
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
													{ label: "Delete", icon: <Trash2 />, destructive: true, onClick: () => handleDeleteThread(thread.id) },
												]}
											/>
										</SidebarMenuItem>
									);
								})}
							</SidebarMenu>
						</SidebarGroupContent>
					</SidebarGroup>

					<SidebarGroup className="mt-auto pt-3">
						<SidebarGroupLabel className="font-[family-name:var(--font-dm-sans)] text-[10.5px] font-semibold uppercase tracking-[0.06em] text-sidebar-section-label">
							Workspace
						</SidebarGroupLabel>
						<SidebarGroupContent>
							<SidebarMenu>
								{navItems.map((item) => {
									const isNavActive = pathname === item.href;
									return (
										<SidebarMenuItem key={item.href}>
											<SidebarMenuButton
												asChild
												isActive={isNavActive}
												tooltip={item.title}
												className="rounded-[14px] transition-all duration-200 hover:translate-x-0.5 hover:bg-sidebar-hover data-[active=true]:bg-sidebar-accent"
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

				<SidebarFooter className="px-3 pb-3">
					<SidebarMenu>
						<SidebarMenuItem>
							<SageDropdownMenu
								trigger={
									<SidebarMenuButton
										size="lg"
										tooltip={user?.name || "User"}
										className="rounded-[18px] bg-sidebar-hover data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground cursor-pointer px-3 py-2.5 group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:bg-transparent group-data-[collapsible=icon]:size-10! group-data-[collapsible=icon]:p-0! group-data-[collapsible=icon]:mx-auto"
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
									{ label: "Settings", icon: <Settings />, onClick: () => router.push("/settings") },
									{ label: "Documentation", icon: <BookOpen />, onClick: () => window.open("https://auxilia-docs.vercel.app/", "_blank") },
									{ label: resolvedTheme === "dark" ? "Light mode" : "Dark mode", icon: resolvedTheme === "dark" ? <Sun /> : <Moon />, onClick: () => setTheme(resolvedTheme === "dark" ? "light" : "dark") },
									{ separator: true },
									{ label: "Log out", icon: <LogOut />, destructive: true, onClick: handleLogout },
								]}
							/>
						</SidebarMenuItem>
					</SidebarMenu>
				</SidebarFooter>
			</Sidebar>
		</>
	);
}

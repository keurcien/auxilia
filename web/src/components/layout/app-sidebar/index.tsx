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
} from "@/components/ui/sidebar";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { useAgentsStore } from "@/stores/agents-store";
import { api } from "@/lib/api/client";
import { ThemeToggle } from "./theme-toggle";

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
			<Sidebar variant="floating" className="font-chat">
				<SidebarHeader>
					<div className="flex items-center gap-1 px-2 py-2">
						<div className="flex size-8 items-center justify-center rounded-lg text-primary-foreground">
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
						</div>
						<div className="flex flex-col">
							<span className="font-sans text-base font-semibold">auxilia</span>
						</div>
					</div>
				</SidebarHeader>

				<SidebarContent>
					<SidebarGroup>
						<button
							onClick={() => {
								if (agents.length > 0) {
									router.push(`/agents/${agents[0].id}/chat`);
								}
							}}
							disabled={agents.length === 0}
							className="w-full py-2.5 px-3.5 rounded-xl border-[1.5px] border-sidebar-border bg-background text-sm font-medium flex items-center justify-center gap-2 cursor-pointer hover:bg-sidebar-accent transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
						>
							<SquarePen className="size-4" />
							New thread
						</button>
					</SidebarGroup>

					<SidebarGroup className="flex-1 min-h-0 overflow-hidden">
						<SidebarGroupContent className="overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							<SidebarMenu>
								{threads.map((thread) => (
									<SidebarMenuItem key={thread.id}>
										<SidebarMenuButton
											asChild
											isActive={
												pathname ===
												`/agents/${thread.agentId}/chat/${thread.id}`
											}
											tooltip={thread.firstMessageContent}
											className="h-auto"
										>
											<Link
												href={`/agents/${thread.agentId}/chat/${thread.id}`}
												className="p-1"
											>
												<div className="flex-1 min-w-0 text-left">
													<div className="text-sm font-medium truncate">
														{thread.firstMessageContent}
													</div>
													<div className="text-xs text-muted-foreground truncate flex items-center gap-1">
														<Bot className="size-3 shrink-0" />
														{thread.agentName}
													</div>
												</div>
												{/* Check for a dot in the thread ID. If it exists, it means the thread was initiated in Slack. But need refactor this to use the thread type instead.*/}
												{thread.id.includes(".") && (
													<Image
														src="https://storage.googleapis.com/choose-assets/slack.png"
														alt="Slack"
														height={16}
														width={16}
														className="h-4 w-4 shrink-0 ml-1"
														title="Thread initiated in Slack"
													/>
												)}
											</Link>
										</SidebarMenuButton>
										<DropdownMenu>
											<DropdownMenuTrigger asChild>
												<SidebarMenuAction
													showOnHover
													className="cursor-pointer"
												>
													<MoreVertical className="size-4" />
													<span className="sr-only">More options</span>
												</SidebarMenuAction>
											</DropdownMenuTrigger>
											<DropdownMenuContent side="right" align="start">
												<DropdownMenuItem
													className="text-destructive focus:text-destructive"
													onClick={() => handleDeleteThread(thread.id)}
												>
													<Trash2 className="size-4 mr-2" />
													<span>Delete</span>
												</DropdownMenuItem>
											</DropdownMenuContent>
										</DropdownMenu>
									</SidebarMenuItem>
								))}
							</SidebarMenu>
						</SidebarGroupContent>
					</SidebarGroup>

					<SidebarGroup className="mt-auto border-t border-sidebar-border pt-3">
						<SidebarGroupLabel className="text-[10.5px] font-semibold uppercase tracking-wide text-muted-foreground">
							Workspace
						</SidebarGroupLabel>
						<SidebarGroupContent>
							<SidebarMenu>
								{navItems.map((item) => (
									<SidebarMenuItem key={item.href}>
										<SidebarMenuButton
											asChild
											isActive={pathname === item.href}
											tooltip={item.title}
										>
											<Link href={item.href}>
												<item.icon />
												<span>{item.title}</span>
											</Link>
										</SidebarMenuButton>
									</SidebarMenuItem>
								))}
							</SidebarMenu>
						</SidebarGroupContent>
					</SidebarGroup>
				</SidebarContent>

				<SidebarFooter className="border-t border-sidebar-border">
					<SidebarMenu>
						<SidebarMenuItem>
							<DropdownMenu>
								<DropdownMenuTrigger asChild>
									<SidebarMenuButton
										size="lg"
										className="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground cursor-pointer"
									>
										<Avatar className="h-8 w-8 rounded-lg">
											<AvatarFallback className="rounded-lg">
												{getInitials(user?.name ?? undefined)}
											</AvatarFallback>
										</Avatar>
										<div className="grid flex-1 text-left text-sm leading-tight">
											<span className="truncate font-medium">
												{user?.name || "User"}
											</span>
											<span className="truncate text-xs">
												{user?.email || ""}
											</span>
										</div>
									</SidebarMenuButton>
								</DropdownMenuTrigger>
								<DropdownMenuContent
									className="w-(--radix-dropdown-menu-trigger-width) min-w-56 rounded-lg"
									side="bottom"
									align="end"
									sideOffset={4}
								>
									<DropdownMenuItem
										onClick={() =>
											window.open("https://auxilia-docs.vercel.app/", "_blank")
										}
										className="cursor-pointer"
									>
										<Settings className="mr-2 h-4 w-4" />
										Settings
									</DropdownMenuItem>
									<DropdownMenuItem
										onClick={() =>
											window.open("https://auxilia-docs.vercel.app/", "_blank")
										}
										className="cursor-pointer"
									>
										<BookOpen className="mr-2 h-4 w-4" />
										Documentation
									</DropdownMenuItem>
									<ThemeToggle />
									<DropdownMenuItem
										onClick={handleLogout}
										className="cursor-pointer"
									>
										<LogOut className="mr-2 h-4 w-4" />
										Log out
									</DropdownMenuItem>
								</DropdownMenuContent>
							</DropdownMenu>
						</SidebarMenuItem>
					</SidebarMenu>
				</SidebarFooter>
			</Sidebar>
		</>
	);
}

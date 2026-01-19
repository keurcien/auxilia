"use client";

import * as React from "react";
import { useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
	Bot,
	Server,
	SquarePen,
	MoreVertical,
	Trash2,
	LogOut,
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

import { NewThreadDialog } from "@/components/layout/app-sidebar/new-thread-dialog";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { api } from "@/lib/api/client";

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
	const pathname = usePathname();
	const [open, setOpen] = React.useState(false);
	const { threads, fetchThreads, removeThread } = useThreadsStore();
	const { user, fetchUser, logout } = useUserStore();

	useEffect(() => {
		fetchUser();
		fetchThreads();
	}, [fetchUser, fetchThreads]);

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
			<Sidebar>
				<SidebarHeader>
					<div className="flex items-center gap-2 px-2 py-2">
						<div className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
							<Bot className="size-4" />
						</div>
						<div className="flex flex-col">
							<span className="text-sm font-semibold">auxilia</span>
							<span className="text-xs text-muted-foreground">AI Platform</span>
						</div>
					</div>
				</SidebarHeader>

				<SidebarContent>
					<SidebarGroup>
						<SidebarMenu>
							<SidebarMenuItem>
								<SidebarMenuButton
									tooltip="New thread"
									onClick={() => setOpen(true)}
									className="cursor-pointer"
								>
									<SquarePen />
									<span>New thread</span>
								</SidebarMenuButton>
							</SidebarMenuItem>
						</SidebarMenu>
					</SidebarGroup>

					<SidebarGroup className="flex-1 min-h-0 overflow-hidden">
						<SidebarGroupLabel>Chat History</SidebarGroupLabel>
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
										>
											<Link
												href={`/agents/${thread.agentId}/chat/${thread.id}`}
											>
												<span className="truncate">
													{thread.firstMessageContent}
												</span>
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

					<SidebarGroup className="mt-auto">
						<SidebarGroupLabel>Workspace</SidebarGroupLabel>
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

				<SidebarFooter>
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

			<NewThreadDialog open={open} onOpenChange={setOpen} />
		</>
	);
}

"use client";

import { usePathname } from "next/navigation";

import { ChatHeader } from "@/components/layout/chat-header";
import { SupervisionBanner } from "@/components/layout/supervision-banner";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { useUserStore } from "@/stores/user-store";
import { cn } from "@/lib/utils";

// Chat is the only surface that keeps the floating card; workspace list
// pages own their full-height chrome (top bar + scroll) via WorkspacePage,
// the agent editor (/agents/new, /agents/{id}) its own two-panel shell, and
// the MCP server subpages (add / custom / detail) their SubpageHeader shell;
// every other route renders in the default padded scroll container.
const CHAT_ROUTE = /^\/agents\/[^/]+\/chat(\/|$)/;
const WORKSPACE_ROUTE = /^\/(agents|users)$/;
const AGENT_EDITOR_ROUTE = /^\/agents\/[^/]+$/;
const MCP_SERVERS_ROUTE = /^\/mcp-servers(\/|$)/;
const TRIGGERS_ROUTE = /^\/triggers(\/|$)/;
const PROJECTS_ROUTE = /^\/projects\/[^/]+(\/|$)/;
const SETTINGS_ROUTE = /^\/settings(\/|$)/;

export function PageShell({ children }: { children: React.ReactNode }) {
	const pathname = usePathname();
	const isSupervising = useUserStore(
		(state) => Boolean(state.user?.supervision),
	);
	const isChat = CHAT_ROUTE.test(pathname);
	const isWorkspace =
		WORKSPACE_ROUTE.test(pathname) ||
		AGENT_EDITOR_ROUTE.test(pathname) ||
		MCP_SERVERS_ROUTE.test(pathname) ||
		TRIGGERS_ROUTE.test(pathname) ||
		PROJECTS_ROUTE.test(pathname) ||
		SETTINGS_ROUTE.test(pathname);

	return (
		<>
			{/* On desktop the collapse control lives in the sidebar; below md the
			    sidebar is an off-canvas sheet that needs an out-of-sheet control to
			    reopen it. This floating chip is hidden on desktop, so the desktop
			    layout is unchanged. */}
			{!isChat && (
				<SidebarTrigger
					className={cn(
						"fixed left-3 z-50 size-9 cursor-pointer rounded-lg border border-sidebar-border bg-sidebar shadow-raised md:hidden",
						isSupervising ? "top-[51px]" : "top-[7px]",
					)}
				/>
			)}

			{isChat ? (
				<main className="flex-1 min-w-0 flex h-svh flex-col bg-background overflow-hidden">
					<SupervisionBanner />
					<ChatHeader />
					<div className="flex flex-1 flex-col min-h-0 overflow-hidden">
						{children}
					</div>
				</main>
			) : isWorkspace ? (
				<main className="flex h-svh min-w-0 flex-1 flex-col overflow-hidden">
					<SupervisionBanner />
					<div className="flex min-h-0 flex-1 overflow-hidden [&>*]:!h-full">
						{children}
					</div>
				</main>
			) : (
				<main className="flex h-svh min-w-0 flex-1 flex-col overflow-hidden">
					<SupervisionBanner />
					<div className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:none] [&>*]:!h-full [&::-webkit-scrollbar]:hidden">
						{children}
					</div>
				</main>
			)}
		</>
	);
}

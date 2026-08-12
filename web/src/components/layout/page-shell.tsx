"use client";

import { usePathname } from "next/navigation";

import { ChatHeader } from "@/components/layout/chat-header";
import { SidebarTrigger } from "@/components/ui/sidebar";

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
const SETTINGS_ROUTE = /^\/settings(\/|$)/;

export function PageShell({ children }: { children: React.ReactNode }) {
	const pathname = usePathname();
	const isChat = CHAT_ROUTE.test(pathname);
	const isWorkspace =
		WORKSPACE_ROUTE.test(pathname) ||
		AGENT_EDITOR_ROUTE.test(pathname) ||
		MCP_SERVERS_ROUTE.test(pathname) ||
		TRIGGERS_ROUTE.test(pathname) ||
		SETTINGS_ROUTE.test(pathname);

	return (
		<>
			{/* On desktop the collapse control lives in the sidebar; below md the
			    sidebar is an off-canvas sheet that needs an out-of-sheet control to
			    reopen it. This floating chip is hidden on desktop, so the desktop
			    layout is unchanged. */}
			<SidebarTrigger className="md:hidden fixed left-3 top-3 z-50 size-9 rounded-lg border border-sidebar-border bg-sidebar shadow-raised cursor-pointer" />

			{isChat ? (
				<main className="flex-1 min-w-0 flex h-svh flex-col bg-background overflow-hidden">
					<ChatHeader />
					<div className="flex flex-1 flex-col min-h-0 overflow-hidden">
						{children}
					</div>
				</main>
			) : isWorkspace ? (
				<main className="flex-1 min-w-0 h-svh overflow-hidden flex">
					{children}
				</main>
			) : (
				<main className="flex-1 min-w-0 h-svh overflow-y-auto pt-16 px-4 pb-6 sm:px-6 md:pt-6 lg:px-8 lg:pb-10 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{children}
				</main>
			)}
		</>
	);
}

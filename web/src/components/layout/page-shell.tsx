"use client";

import { usePathname } from "next/navigation";

import { ChatHeader } from "@/components/layout/chat-header";
import { SidebarTrigger } from "@/components/ui/sidebar";

// Chat is the only surface that keeps the floating white card; every other
// route renders straight onto the sage canvas with the shared content padding.
const CHAT_ROUTE = /^\/agents\/[^/]+\/chat(\/|$)/;

export function PageShell({ children }: { children: React.ReactNode }) {
	const pathname = usePathname();
	const isChat = CHAT_ROUTE.test(pathname);

	return (
		<>
			{/* On desktop the collapse control lives in the sidebar; below md the
			    sidebar is an off-canvas sheet that needs an out-of-sheet control to
			    reopen it. This floating chip is hidden on desktop, so the desktop
			    layout is unchanged. */}
			<SidebarTrigger className="md:hidden fixed left-3 top-3 z-50 size-9 rounded-lg border border-sidebar-border bg-sidebar shadow-[0_1px_3px_rgba(30,45,40,0.05)] cursor-pointer" />

			{isChat ? (
				<main className="flex-1 min-w-0 flex h-svh p-2 pl-0">
					<div className="flex-1 min-w-0 flex flex-col rounded-2xl border border-border bg-card shadow-[0_1px_3px_rgba(30,45,40,0.05)] overflow-hidden">
						<ChatHeader />
						<div className="flex flex-1 flex-col min-h-0 overflow-hidden">
							{children}
						</div>
					</div>
				</main>
			) : (
				<main className="flex-1 min-w-0 h-svh overflow-y-auto pt-16 px-4 pb-6 sm:px-6 md:pt-6 lg:px-8 lg:pb-10 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{children}
				</main>
			)}
		</>
	);
}

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

	if (isChat) {
		return (
			<main className="flex-1 min-w-0 flex h-svh p-2 pl-0">
				<div className="flex-1 min-w-0 flex flex-col rounded-2xl border border-border bg-card shadow-[0_1px_3px_rgba(30,45,40,0.05)] overflow-hidden">
					{/* Mobile-only: the desktop trigger lives in the sidebar, but on
					    mobile the sidebar is an off-canvas sheet that needs an
					    out-of-sheet control to reopen it. */}
					<div className="md:hidden flex h-12 shrink-0 items-center border-b border-border px-2">
						<SidebarTrigger className="cursor-pointer" />
					</div>
					<ChatHeader />
					<div className="flex flex-1 flex-col min-h-0 overflow-hidden">
						{children}
					</div>
				</div>
			</main>
		);
	}

	return (
		<main className="flex-1 min-w-0 h-svh overflow-y-auto pt-4 px-4 pb-6 sm:px-6 lg:px-8 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
			<SidebarTrigger className="md:hidden mb-2 cursor-pointer" />
			{children}
		</main>
	);
}

import { cookies } from "next/headers";

import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { StoreInitializer } from "@/components/providers/store-initializer";
import { ChatHeader } from "@/components/layout/chat-header";

export default async function ProtectedLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	const cookieStore = await cookies();
	const defaultOpen = cookieStore.get("sidebar_state")?.value === "true";

	return (
		<SidebarProvider defaultOpen={defaultOpen} className="bg-surface">
			<StoreInitializer />
			<AppSidebar />
			<main className="flex-1 min-w-0 flex h-svh p-2 pl-0">
				<div className="flex-1 min-w-0 flex flex-col rounded-2xl border border-border bg-card shadow-[0_1px_3px_rgba(30,45,40,0.05)] overflow-hidden">
					<div className="flex items-center gap-2 px-5 h-14 shrink-0 border-b border-border">
						<SidebarTrigger className="cursor-pointer" />
						<ChatHeader />
					</div>
					<div className="flex flex-1 flex-col gap-4 lg:px-8 px-4 py-5 min-h-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
						{children}
					</div>
				</div>
			</main>
		</SidebarProvider>
	);
}

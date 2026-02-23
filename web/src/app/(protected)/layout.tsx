import { cookies } from "next/headers";

import { SidebarProvider, SidebarTrigger } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { StoreInitializer } from "@/components/providers/store-initializer";

export default async function ProtectedLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	const cookieStore = await cookies();
	const defaultOpen = cookieStore.get("sidebar_state")?.value === "true";

	return (
		<SidebarProvider defaultOpen={defaultOpen}>
			<StoreInitializer />
			<AppSidebar />
			<main className="flex-1 flex flex-col h-screen w-full">
				<div className="flex items-center gap-2 p-4 shrink-0">
					<SidebarTrigger className="cursor-pointer" />
				</div>
				<div className="flex flex-1 flex-col gap-4 lg:px-8 px-4 py-4 pt-0 min-h-0 overflow-y-auto">
					{children}
				</div>
			</main>
		</SidebarProvider>
	);
}

import { cookies } from "next/headers";

import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { StoreInitializer } from "@/components/providers/store-initializer";
import { PageShell } from "@/components/layout/page-shell";

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
			<PageShell>{children}</PageShell>
		</SidebarProvider>
	);
}

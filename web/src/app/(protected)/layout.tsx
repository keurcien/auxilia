import { cookies } from "next/headers";

import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { PageShell } from "@/components/layout/page-shell";
import { WorkspacesProvider } from "@/components/providers/workspaces-provider";

export default async function ProtectedLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	const cookieStore = await cookies();
	const defaultOpen = cookieStore.get("sidebar_state")?.value === "true";

	return (
		<WorkspacesProvider>
			<SidebarProvider defaultOpen={defaultOpen} className="bg-surface">
				<AppSidebar />
				<PageShell>{children}</PageShell>
			</SidebarProvider>
		</WorkspacesProvider>
	);
}

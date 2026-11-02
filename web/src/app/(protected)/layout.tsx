import { cookies } from "next/headers";

import { SidebarProvider } from "@/components/ui/sidebar";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { PageShell } from "@/components/layout/page-shell";
import { WorkspacesProvider } from "@/components/providers/workspaces-provider";
import { McpOAuthProvider } from "@/components/providers/mcp-oauth-provider";
import { PromptInputProvider } from "@/components/ai-elements/prompt-input";

export default async function ProtectedLayout({
	children,
}: {
	children: React.ReactNode;
}) {
	const cookieStore = await cookies();
	const defaultOpen = cookieStore.get("sidebar_state")?.value !== "false";

	return (
		<WorkspacesProvider>
			<McpOAuthProvider>
				<PromptInputProvider>
					<SidebarProvider defaultOpen={defaultOpen} className="bg-surface">
						<AppSidebar />
						<PageShell>{children}</PageShell>
					</SidebarProvider>
				</PromptInputProvider>
			</McpOAuthProvider>
		</WorkspacesProvider>
	);
}

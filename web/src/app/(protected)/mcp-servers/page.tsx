"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import MCPServerTable from "@/app/(protected)/mcp-servers/components/mcp-server-table";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { useUserStore } from "@/stores/user-store";

export default function MCPServersPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const [search, setSearch] = useQueryParamState("q");
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);

	const handleAddServer = () => {
		if (!user) return;
		if (user.role !== "admin") {
			setErrorDialogOpen(true);
			return;
		}
		router.push("/mcp-servers/add");
	};

	return (
		<WorkspacePage
			slug="mcp-servers"
			title="MCP servers"
			intro="Remote Model Context Protocol endpoints wired into your workspace."
			fillHeight
			search={{
				placeholder: "Search servers…",
				value: search,
				onChange: setSearch,
			}}
			actions={
				<WorkspaceTopBarButton
					// Until /auth/me resolves the role check can't run — a click
					// would silently no-op, so keep the button disabled.
					disabled={!user}
					onClick={() => {
						handleAddServer();
					}}
				>
					<Plus className="size-3.5" />
					Add MCP server
				</WorkspaceTopBarButton>
			}
		>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You need admin permissions to add MCP servers."
			/>
			<MCPServerTable
				search={search}
				onClearSearch={() => {
					setSearch("");
				}}
			/>
		</WorkspacePage>
	);
}

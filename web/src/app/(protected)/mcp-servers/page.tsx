"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import { Plus, RefreshCw } from "lucide-react";
import MCPServerTable from "@/app/(protected)/mcp-servers/components/mcp-server-table";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { HeaderButton } from "@/components/layout/subpage-header";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { api } from "@/lib/api/client";
import { useUserStore } from "@/stores/user-store";
import { MCPCatalogSyncResult } from "@/types/mcp-servers";

function syncSummary(result: MCPCatalogSyncResult): string {
	const changes = [
		result.added.length > 0 && `${result.added.length} added`,
		result.removed.length > 0 && `${result.removed.length} removed`,
	]
		.filter(Boolean)
		.join(", ");
	return `Catalog synced — ${changes || "no changes"} (${result.serverCount} servers).`;
}

function apiErrorDetail(error: unknown): string | null {
	if (axios.isAxiosError(error)) {
		const data = error.response?.data as { detail?: string } | undefined;
		return data?.detail ?? null;
	}
	return null;
}

export default function MCPServersPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";
	const [search, setSearch] = useQueryParamState("q");
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [isSyncing, setIsSyncing] = useState(false);
	const [syncStatus, setSyncStatus] = useState<{
		kind: "info" | "error";
		text: string;
	} | null>(null);

	// The catalog is CDN-hosted with a long cache TTL, so a newly published
	// server only shows up once an admin pulls it in.
	const handleSyncCatalog = async () => {
		setIsSyncing(true);
		setSyncStatus(null);
		try {
			const response = await api.post<MCPCatalogSyncResult>(
				"/mcp-servers/catalog/sync",
			);
			setSyncStatus({ kind: "info", text: syncSummary(response.data) });
		} catch (error: unknown) {
			setSyncStatus({
				kind: "error",
				text: apiErrorDetail(error) ?? "Catalog sync failed. Please retry.",
			});
		} finally {
			setIsSyncing(false);
		}
	};

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
				<>
					{isAdmin && (
						<HeaderButton
							accent
							className="gap-1.5 px-3.5 py-[7px] text-[12.5px]"
							disabled={isSyncing}
							onClick={() => {
								void handleSyncCatalog();
							}}
						>
							<RefreshCw
								className={
									isSyncing ? "size-[13px] animate-spin" : "size-[13px]"
								}
							/>
							Sync catalog
						</HeaderButton>
					)}
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
				</>
			}
		>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You need admin permissions to add MCP servers."
			/>
			{syncStatus && (
				<p
					className={`mb-3 shrink-0 text-[13px] font-medium ${
						syncStatus.kind === "error"
							? "text-destructive"
							: "text-subtle dark:text-panel-body"
					}`}
				>
					{syncStatus.text}
				</p>
			)}
			<MCPServerTable
				search={search}
				onClearSearch={() => {
					setSearch("");
				}}
			/>
		</WorkspacePage>
	);
}

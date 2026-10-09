"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, RefreshCw } from "lucide-react";
import MCPServerTable from "@/app/(protected)/mcp-servers/components/mcp-server-table";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { HeaderButton } from "@/components/layout/subpage-header";
import { ResourceScopeFilterDropdown } from "@/components/ui/resource-scope-filter";
import { ViewToggle } from "@/components/ui/view-toggle";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { usePersistedViewMode } from "@/hooks/use-persisted-view-mode";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { isApiError } from "@/lib/api/errors";
import type { ResourceScopeFilter } from "@/lib/resource-scope-filter";
import { useUserStore } from "@/stores/user-store";
import { MCPCatalogSyncResult } from "@/types/mcp-servers";

function syncSummary(result: MCPCatalogSyncResult): string {
	const changes = [
		result.added.length > 0 && `${result.added.length} added`,
		result.removed.length > 0 && `${result.removed.length} removed`,
	]
		.filter(Boolean)
		.join(", ");
	return `Catalog synced, ${changes || "no changes"} (${result.serverCount} servers).`;
}

function apiErrorDetail(error: unknown): string | null {
	return isApiError(error) ? error.detail : null;
}

export default function MCPServersPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";
	const [search, setSearch] = useQueryParamState("q");
	const [scopeParam, setScopeParam] = useQueryParamState("scope", "all");
	const [teamParam, setTeamParam] = useQueryParamState("teams");
	const scope: ResourceScopeFilter =
		scopeParam === "personal" ||
		scopeParam === "workspace" ||
		scopeParam === "teams"
			? scopeParam
			: "all";
	const filterTeamIds = teamParam.split(",").filter(Boolean);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [isSyncing, setIsSyncing] = useState(false);
	const [syncStatus, setSyncStatus] = useState<{
		kind: "info" | "error";
		text: string;
	} | null>(null);
	const [viewMode, setViewMode] = usePersistedViewMode("mcp-servers:view-mode");

	// The catalog is CDN-hosted with a long cache TTL, so a newly published
	// server only shows up once an admin pulls it in.
	const handleSyncCatalog = async () => {
		setIsSyncing(true);
		setSyncStatus(null);
		try {
			const result = await mcpServersApi.syncMcpCatalog();
			setSyncStatus({ kind: "info", text: syncSummary(result) });
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
			fillHeight={viewMode === "table"}
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
							aria-label="Sync catalog"
							title="Sync catalog"
							className="size-9 justify-center p-0 text-[12.5px] lg:h-auto lg:w-auto lg:px-3.5 lg:py-[7px]"
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
							<span className="hidden lg:inline">Sync catalog</span>
						</HeaderButton>
					)}
					<WorkspaceTopBarButton
						aria-label="Add MCP server"
						title="Add MCP server"
						className="size-9 justify-center p-0 lg:h-auto lg:w-auto lg:px-[18px] lg:py-[9px]"
						// Until /auth/me resolves the role check can't run — a click
						// would silently no-op, so keep the button disabled.
						disabled={!user}
						onClick={() => {
							handleAddServer();
						}}
					>
						<Plus className="size-3.5" />
						<span className="hidden lg:inline">Add MCP server</span>
					</WorkspaceTopBarButton>
				</>
			}
			headerRight={
				<div className="flex w-full min-w-0 items-center gap-3">
					<ResourceScopeFilterDropdown
						value={scope}
						teamIds={filterTeamIds}
						onChange={(next, teamIds) => {
							setScopeParam(next);
							setTeamParam(teamIds.join(","));
						}}
					/>
					<ViewToggle
						value={viewMode}
						onChange={setViewMode}
						className="ml-auto"
					/>
				</div>
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
				mode={viewMode}
				search={search}
				scope={scope}
				filterTeamIds={filterTeamIds}
				onClearSearch={() => {
					setSearch("");
				}}
			/>
		</WorkspacePage>
	);
}

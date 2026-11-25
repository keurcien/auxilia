"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import MCPServerTable from "@/app/(protected)/mcp-servers/components/mcp-server-table";
import {
	CredentialScopeFilterDropdown,
	parseCredentialScopeFilter,
} from "@/app/(protected)/mcp-servers/components/credential-scope-filter";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { ResourceScopeFilterDropdown } from "@/components/ui/resource-scope-filter";
import { ViewToggle } from "@/components/ui/view-toggle";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { usePersistedViewMode } from "@/hooks/use-persisted-view-mode";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import type { ResourceScopeFilter } from "@/lib/resource-scope-filter";
import { useUserStore } from "@/stores/user-store";

export default function MCPServersPage() {
	const user = useUserStore((state) => state.user);
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
	const [credentialsParam, setCredentialsParam] = useQueryParamState(
		"credentials",
		"all",
	);
	const credentialScope = parseCredentialScopeFilter(credentialsParam);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [viewMode, setViewMode] = usePersistedViewMode("mcp-servers:view-mode");

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
				<WorkspaceTopBarButton
					aria-label="Add MCP server"
					title="Add MCP server"
					className="size-9 justify-center p-0 lg:h-auto lg:w-auto lg:px-[18px] lg:py-[9px]"
					// Until /auth/me resolves the role check can't run, so keep it
					// disabled rather than letting a click silently do nothing.
					disabled={!user}
					href={user?.role === "admin" ? "/mcp-servers/add" : undefined}
					onClick={() => {
						if (user && user.role !== "admin") setErrorDialogOpen(true);
					}}
				>
					<Plus className="size-3.5" />
					<span className="hidden lg:inline">Add MCP server</span>
				</WorkspaceTopBarButton>
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
					<CredentialScopeFilterDropdown
						value={credentialScope}
						onChange={setCredentialsParam}
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
			<MCPServerTable
				mode={viewMode}
				search={search}
				scope={scope}
				filterTeamIds={filterTeamIds}
				credentialScope={credentialScope}
				onClearSearch={() => {
					setSearch("");
				}}
			/>
		</WorkspacePage>
	);
}

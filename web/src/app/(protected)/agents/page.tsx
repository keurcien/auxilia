"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import AgentList from "@/app/(protected)/agents/components/agent-list";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { ResourceScopeFilterDropdown } from "@/components/ui/resource-scope-filter";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { ViewToggle } from "@/components/ui/view-toggle";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { useUserStore } from "@/stores/user-store";
import { useAgentsStore } from "@/stores/agents-store";
import { usePersistedViewMode } from "@/hooks/use-persisted-view-mode";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import * as agentsApi from "@/lib/api/resources/agents";
import type { ResourceScopeFilter } from "@/lib/resource-scope-filter";
import type { Agent } from "@/types/agents";

const VIEW_MODE_STORAGE_KEY = "agents:view-mode";

export default function AgentsPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [search, setSearch] = useQueryParamState("q");
	const [viewParam, setView] = useQueryParamState("view", "all");
	const [teamParam, setTeamParam] = useQueryParamState("teams");
	const activeAgents = useAgentsStore((state) => state.agents);
	const [archivedAgents, setArchivedAgents] = useState<Agent[] | null>(null);
	const view: ResourceScopeFilter | "archived" =
		viewParam === "all" ||
		viewParam === "personal" ||
		viewParam === "workspace" ||
		viewParam === "teams" ||
		viewParam === "archived"
			? viewParam
			: "all";
	const filterTeamIds = teamParam.split(",").filter(Boolean);
	const [viewMode, setViewMode] = usePersistedViewMode(VIEW_MODE_STORAGE_KEY);

	useEffect(() => {
		void agentsApi
			.listArchivedAgents()
			.then(setArchivedAgents)
			.catch(() => {
				setArchivedAgents([]);
			});
	}, []);

	const handleCreateAgent = () => {
		if (!user) return;
		if (user.role === "member") {
			setErrorDialogOpen(true);
			return;
		}
		router.push("/agents/new");
	};

	return (
		<WorkspacePage
			slug="agents"
			title="Agents"
			intro="Assistants connected to your team's tools. Chat with them, or let triggers run them on a schedule."
			fillHeight={viewMode === "table"}
			search={{
				placeholder: "Search agents…",
				value: search,
				onChange: setSearch,
			}}
			actions={
				<WorkspaceTopBarButton
					aria-label="New agent"
					title="New agent"
					className="size-9 justify-center p-0 lg:h-auto lg:w-auto lg:px-[18px] lg:py-[9px]"
					// Until /auth/me resolves the role check can't run — a click
					// would silently no-op, so keep the button disabled.
					disabled={!user}
					onClick={() => {
						handleCreateAgent();
					}}
				>
					<Plus className="size-3.5" />
					<span className="hidden lg:inline">New agent</span>
				</WorkspaceTopBarButton>
			}
			headerRight={
				<div className="flex w-full min-w-0 items-center gap-3">
					<UnderlineTabs
						tabs={[
							{ key: "active", label: "Active", count: activeAgents.length },
							{
								key: "archived",
								label: "Archived",
								count: archivedAgents?.length,
							},
						]}
						value={view === "archived" ? "archived" : "active"}
						onChange={(next) => {
							setView(next === "archived" ? "archived" : "all");
						}}
					/>
					<ResourceScopeFilterDropdown
						value={view === "archived" ? "all" : view}
						teamIds={filterTeamIds}
						onChange={(next, teamIds) => {
							setView(next);
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
				message="You need at least editor permissions to create agents."
			/>
			<AgentList
				key={view === "archived" ? "archived" : "active"}
				view={view}
				mode={viewMode}
				search={search}
				filterTeamIds={filterTeamIds}
				archivedAgents={archivedAgents ?? []}
				archivedLoading={archivedAgents === null}
				onArchivedAgentsChange={setArchivedAgents}
				onClearSearch={() => {
					setSearch("");
				}}
				onCreateAgent={() => {
					handleCreateAgent();
				}}
			/>
		</WorkspacePage>
	);
}

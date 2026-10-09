"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import TriggerList from "@/app/(protected)/triggers/components/trigger-list";
import { ResourceScopeFilterDropdown } from "@/components/ui/resource-scope-filter";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { ViewToggle } from "@/components/ui/view-toggle";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { usePersistedViewMode } from "@/hooks/use-persisted-view-mode";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import type { ResourceScopeFilter } from "@/lib/resource-scope-filter";
import { useTriggersStore } from "@/stores/triggers-store";
import { useUserStore } from "@/stores/user-store";

export default function TriggersPage() {
	const router = useRouter();
	const canCreate = useUserStore(
		(state) => state.user !== null && state.user.role !== "member",
	);
	const triggers = useTriggersStore((state) => state.triggers);
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
	const [view, setView] = useState<"active" | "paused">("active");
	const [viewMode, setViewMode] = usePersistedViewMode("triggers:view-mode");

	const activeCount = triggers.filter((trigger) => trigger.isActive).length;
	const pausedCount = triggers.length - activeCount;

	const handleCreate = () => {
		router.push("/triggers/new");
	};

	return (
		<WorkspacePage
			slug="triggers"
			title="Triggers"
			intro="Run agents automatically on a schedule or from an external webhook."
			fillHeight={viewMode === "table"}
			fullWidth
			search={{
				placeholder: "Search triggers…",
				value: search,
				onChange: setSearch,
			}}
			actions={canCreate ? (
				<WorkspaceTopBarButton
					aria-label="New trigger"
					title="New trigger"
					className="size-9 justify-center p-0 lg:h-auto lg:w-auto lg:px-[18px] lg:py-[9px]"
					onClick={() => {
						handleCreate();
					}}
				>
					<Plus className="size-3.5" />
					<span className="hidden lg:inline">New trigger</span>
				</WorkspaceTopBarButton>
			) : undefined}
			headerRight={
				<div className="flex w-full min-w-0 items-center gap-3">
					<UnderlineTabs
						tabs={[
							{ key: "active", label: "Active", count: activeCount },
							{ key: "paused", label: "Paused", count: pausedCount },
						]}
						value={view}
						onChange={setView}
					/>
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
			<TriggerList
				view={view}
				mode={viewMode}
				onCreate={handleCreate}
				canCreate={canCreate}
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

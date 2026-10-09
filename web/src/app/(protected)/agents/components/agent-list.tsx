"use client";

import { useState, useEffect, useMemo } from "react";
import {
	Archive,
	ChevronRight,
	Folder,
	Plus,
	Search,
	Zap,
} from "lucide-react";
import {
	BulkConfirmDialog,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { BulkActionBar } from "@/components/ui/bulk-action-bar";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import AgentTable from "@/app/(protected)/agents/components/agent-table";
import { buildGroupTree, flattenGroupTree, type GroupNode } from "@/lib/groups";
import { useRowSelection } from "@/hooks/use-row-selection";
import { getApiErrorMessage } from "@/lib/api/errors";
import type { ViewMode } from "@/components/ui/view-toggle";
import { useAgentsStore } from "@/stores/agents-store";
import {
	matchesResourceScope,
	type ResourceScopeFilter,
} from "@/lib/resource-scope-filter";

type View = ResourceScopeFilter | "archived";

function EmptyState({
	icon,
	title,
	subtitle,
	action,
}: {
	icon: React.ReactNode;
	title: string;
	subtitle: string;
	action?: { label: string; icon: React.ReactNode; onClick: () => void };
}) {
	return (
		<div className="flex flex-col items-center justify-center py-16 px-8 animate-in fade-in slide-in-from-bottom-2 duration-400">
			{/* Icon bubble */}
			<div className="w-[72px] h-[72px] rounded-full bg-[#F5F8F6] dark:bg-white/5 flex items-center justify-center mb-5">
				<div className="w-12 h-12 rounded-full bg-[#EDF4F0] dark:bg-white/10 flex items-center justify-center">
					{icon}
				</div>
			</div>

			<div className="font-[family-name:var(--font-jakarta-sans)] text-[17px] font-bold text-[#1E2D28] dark:text-foreground tracking-[-0.01em] mb-1.5">
				{title}
			</div>

			<div className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium text-center max-w-[320px] leading-relaxed mb-6">
				{subtitle}
			</div>

			{action && (
				<button
					onClick={action.onClick}
					className="flex items-center gap-1.5 px-5.5 py-2.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[13.5px] font-semibold text-[#1E2D28] dark:text-foreground cursor-pointer transition-all hover:bg-[#F8FAF9] dark:hover:bg-white/5 hover:-translate-y-0.5"
				>
					{action.icon}
					{action.label}
				</button>
			)}
		</div>
	);
}

function AgentCardGrid({
	agents,
	archived,
	onRemoved,
	selectedIds,
	selectionMode,
	onToggleSelection,
}: {
	agents: Agent[];
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
	selectedIds: Set<string>;
	selectionMode: boolean;
	onToggleSelection: (agentId: string, shiftKey: boolean) => void;
}) {
	return (
		<div
			className="grid gap-4"
			style={{
				gridTemplateColumns:
					"repeat(auto-fill, minmax(min(100%, max(260px, calc((100% - 2rem) / 3))), 1fr))",
			}}
		>
			{agents.map((agent, index) => (
				<div
					key={agent.id}
					className="h-full animate-in fade-in slide-in-from-bottom-3 duration-400"
					style={{
						animationDelay: `${index * 40}ms`,
						animationFillMode: "both",
					}}
				>
					<AgentCard
						agent={agent}
						archived={archived}
						onRemoved={onRemoved}
						selected={selectedIds.has(agent.id)}
						selectionMode={selectionMode}
						onToggleSelection={(shiftKey) => {
							onToggleSelection(agent.id, shiftKey);
						}}
					/>
				</div>
			))}
		</div>
	);
}

function AgentSection({
	node,
	archived,
	onRemoved,
	storageKey,
	selectedIds,
	selectionMode,
	onToggleSelection,
}: {
	node: GroupNode<Agent>;
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
	storageKey: string;
	selectedIds: Set<string>;
	selectionMode: boolean;
	onToggleSelection: (agentId: string, shiftKey: boolean) => void;
}) {
	const [expanded, setExpanded] = useState(() => {
		try {
			return localStorage.getItem(storageKey) !== "0";
		} catch {
			return true;
		}
	});

	const toggle = () => {
		setExpanded((v) => {
			const next = !v;
			try {
				localStorage.setItem(storageKey, next ? "1" : "0");
			} catch {
				// The in-session state still works when persistence is unavailable.
			}
			return next;
		});
	};

	return (
		<section className="animate-in fade-in duration-300">
			<button
				type="button"
				aria-expanded={expanded}
				onClick={toggle}
				style={{ paddingLeft: `${node.depth * 18}px` }}
				className="group mb-3 flex w-full cursor-pointer items-center gap-2 py-1 text-left"
			>
				<ChevronRight
					className={`size-3.5 shrink-0 text-meta transition-transform ${
						expanded ? "rotate-90" : ""
					}`}
				/>
				<Folder className="size-4 shrink-0 text-meta" />
				<h2 className="whitespace-nowrap text-[13.5px] font-bold tracking-[-0.01em] text-foreground">
					{node.name}
				</h2>
				<span className="font-mono text-[11px] text-meta">{node.count}</span>
				<div className="h-px flex-1 bg-[#E8EFE9] dark:bg-white/10" />
			</button>

			{expanded && (
				<div className="mb-6">
					{node.items.length > 0 && (
						<div
							className="mb-4"
							style={{ paddingLeft: `${(node.depth + 1) * 18}px` }}
						>
							<AgentCardGrid
								agents={node.items}
								archived={archived}
								onRemoved={onRemoved}
								selectedIds={selectedIds}
								selectionMode={selectionMode}
								onToggleSelection={onToggleSelection}
							/>
						</div>
					)}
					{node.children.map((child) => (
						<AgentSection
							key={child.path}
							node={child}
							archived={archived}
							onRemoved={onRemoved}
							storageKey={`${storageKey}:${child.path}`}
							selectedIds={selectedIds}
							selectionMode={selectionMode}
							onToggleSelection={onToggleSelection}
						/>
					))}
				</div>
			)}
		</section>
	);
}

interface AgentListProps {
	view: View;
	/** Table or the group-tree card grid. */
	mode: ViewMode;
	search: string;
	filterTeamIds: string[];
	archivedAgents: Agent[];
	archivedLoading: boolean;
	onArchivedAgentsChange: (agents: Agent[]) => void;
	onClearSearch?: () => void;
	onCreateAgent?: () => void;
}

export default function AgentList({
	view,
	mode,
	search,
	filterTeamIds,
	archivedAgents,
	archivedLoading,
	onArchivedAgentsChange,
	onClearSearch,
	onCreateAgent,
}: AgentListProps) {
	const archived = view === "archived";
	// Live views read the shared store (already fetched by the sidebar), so
	// visiting the page never re-requests the list. Archived agents aren't in
	// the store; that view keeps its own fetch.
	const storeAgents = useAgentsStore((state) => state.agents);
	const storeReady = useAgentsStore((state) => state.isInitialized);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const removeAgent = useAgentsStore((state) => state.removeAgent);
	const archiveAgent = useAgentsStore((state) => state.archiveAgent);
	const permanentlyDeleteAgent = useAgentsStore(
		(state) => state.permanentlyDeleteAgent,
	);
	const [bulkOpen, setBulkOpen] = useState(false);

	useEffect(() => {
		if (!archived) fetchAgents().catch(console.error);
	}, [archived, fetchAgents]);

	const agents = archived ? archivedAgents : storeAgents;
	const isLoading = archived ? archivedLoading : !storeReady;

	const handleRemoved = (agentId: string) => {
		if (archived) {
			onArchivedAgentsChange(
				archivedAgents.filter((agent) => agent.id !== agentId),
			);
			return;
		}
		removeAgent(agentId);
	};

	const matches = useMemo(() => {
		if (!search) return agents;
		const query = search.toLowerCase();
		return agents.filter(
			(agent) =>
				agent.name.toLowerCase().includes(query) ||
				(agent.description ?? "").toLowerCase().includes(query) ||
				(agent.group ?? "").toLowerCase().includes(query),
		);
	}, [agents, search]);

	const visible = useMemo(
		() =>
			view === "archived" || view === "all"
				? matches
				: matches.filter((agent) =>
						matchesResourceScope(agent, view, filterTeamIds),
					),
		[filterTeamIds, matches, view],
	);

	const groupTree = useMemo(() => buildGroupTree(visible), [visible]);
	const orderedAgents = useMemo(() => flattenGroupTree(groupTree), [groupTree]);
	const manageableAgentIds = useMemo(
		() =>
			orderedAgents
				.filter(
					(agent) =>
						agent.currentUserPermission === "owner" ||
						agent.currentUserPermission === "admin",
				)
				.map((agent) => agent.id),
		[orderedAgents],
	);
	const selection = useRowSelection({
		orderedIds: orderedAgents.map((agent) => agent.id),
		eligibleIds: manageableAgentIds,
	});
	const selectedAgents = orderedAgents.filter((agent) =>
		selection.selectedIds.has(agent.id),
	);

	const bulkControls = (
		<>
			<BulkActionBar
				selectedCount={selection.selectedCount}
				totalCount={manageableAgentIds.length}
				allSelected={selection.allSelected}
				someSelected={selection.someSelected}
				onToggleAll={selection.toggleAll}
				onClear={selection.clear}
				actionLabel={archived ? "Delete permanently" : "Archive"}
				actionIcon={
					archived ? undefined : <Archive className="size-3.5" />
				}
				onAction={() => {
					setBulkOpen(true);
				}}
				showWhenEmpty={mode === "cards"}
			/>
			<BulkConfirmDialog
				open={bulkOpen}
				onOpenChange={setBulkOpen}
				title={
					archived
						? "Permanently delete selected agents?"
						: "Archive selected agents?"
				}
				description={
					archived
						? "This permanently removes the agents, their tool connections, and every chat thread that used them."
						: "Archived agents stop being available for chat and automations, but can be restored later."
				}
				items={selectedAgents.map((agent) => ({
					id: agent.id,
					name: agent.name,
				}))}
				confirmLabel={archived ? "Delete" : "Archive"}
				busyLabel={archived ? "Deleting…" : "Archiving…"}
				onConfirm={async (items) => {
					const action = archived ? permanentlyDeleteAgent : archiveAgent;
					const results = await Promise.allSettled(
						items.map((item) => action(item.id)),
					);
					const succeeded: string[] = [];
					const failures: BulkFailure[] = [];
					results.forEach((result, index) => {
						const item = items.at(index);
						if (!item) return;
						if (result.status === "fulfilled") succeeded.push(item.id);
						else
							failures.push({
								id: item.id,
								name: item.name,
								message: getApiErrorMessage(result.reason, "Action failed."),
							});
					});
					if (archived && succeeded.length > 0) {
						const removed = new Set(succeeded);
						onArchivedAgentsChange(
							archivedAgents.filter((agent) => !removed.has(agent.id)),
						);
					} else if (succeeded.length > 0) {
						const archivedIds = new Set(succeeded);
						const newlyArchived = selectedAgents
							.filter((agent) => archivedIds.has(agent.id))
							.map((agent) => ({ ...agent, isArchived: true }));
						onArchivedAgentsChange([
							...newlyArchived,
							...archivedAgents.filter(
								(agent) => !archivedIds.has(agent.id),
							),
						]);
					}
					selection.remove(succeeded);
					return failures;
				}}
			/>
		</>
	);

	if (isLoading) return null;

	// Empty archived view.
	if (archived && agents.length === 0) {
		return (
			<EmptyState
				icon={<Archive className="size-[22px] text-[#4CA882]" />}
				title="No archived agents"
				subtitle="Agents you archive show up here, where they can be restored or deleted permanently."
			/>
		);
	}

	// Empty workspace — no agents at all.
	if (agents.length === 0) {
		return (
			<EmptyState
				icon={<Zap className="size-[22px] text-[#4CA882]" />}
				title="Create your first agent"
				subtitle="Agents help your team automate tasks and access your data tools."
				action={
					onCreateAgent
						? {
								label: "Create an agent",
								icon: <Plus className="size-[15px] text-[#4CA882]" />,
								onClick: onCreateAgent,
							}
						: undefined
				}
			/>
		);
	}

	// Search returned nothing the current view can show.
	if (search && visible.length === 0) {
		return (
			<EmptyState
				icon={<Search className="size-[22px] text-[#4CA882]" />}
				title="No agents found"
				subtitle="Try adjusting your search to find what you're looking for."
				action={
					onClearSearch
						? {
								label: "Clear search",
								icon: <Search className="size-[15px] text-[#4CA882]" />,
								onClick: onClearSearch,
							}
						: undefined
				}
			/>
		);
	}

	if (visible.length === 0) {
		return (
			<EmptyState
				icon={<Search className="size-[22px] text-[#4CA882]" />}
				title="No agents match this filter"
				subtitle="Choose another visibility filter."
			/>
		);
	}

	if (mode === "table") {
		// min-h-0 flex chain: lets the table body cap at the remaining page
		// height (WorkspacePage fillHeight) and scroll internally.
		return (
			<div className="flex min-h-0 w-full flex-1 flex-col animate-in fade-in duration-300">
				{bulkControls}
				<AgentTable
					agents={visible}
					archived={archived}
					onRemoved={handleRemoved}
					selectedIds={selection.selectedIds}
					selectionMode={selection.selectionMode}
					onToggleAll={selection.toggleAll}
					onToggleSelection={selection.toggle}
				/>
			</div>
		);
	}

	return (
		<div className="w-full animate-in fade-in duration-300">
			{bulkControls}
			{groupTree.groups.map((group) => (
				<AgentSection
					key={`${view}:${group.path}`}
					node={group}
					archived={archived}
					onRemoved={handleRemoved}
					storageKey={`agents:group:${view}:${group.path}:expanded`}
					selectedIds={selection.selectedIds}
					selectionMode={selection.selectionMode}
					onToggleSelection={selection.toggle}
				/>
			))}
			{groupTree.ungrouped.length > 0 &&
				(groupTree.groups.length > 0 ? (
					<AgentSection
						node={{
							name: "Default",
							path: "__ungrouped__",
							depth: 0,
							items: groupTree.ungrouped,
							children: [],
							count: groupTree.ungrouped.length,
						}}
						archived={archived}
						onRemoved={handleRemoved}
						storageKey={`agents:group:${view}:__ungrouped__:expanded`}
						selectedIds={selection.selectedIds}
						selectionMode={selection.selectionMode}
						onToggleSelection={selection.toggle}
					/>
				) : (
					<AgentCardGrid
						agents={groupTree.ungrouped}
						archived={archived}
						onRemoved={handleRemoved}
						selectedIds={selection.selectedIds}
						selectionMode={selection.selectionMode}
						onToggleSelection={selection.toggle}
					/>
				))}
		</div>
	);
}

"use client";

import { useState, useEffect, useMemo } from "react";
import {
	Archive,
	ChevronRight,
	Folder,
	Plus,
	Search,
	Users,
	Zap,
} from "lucide-react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import AgentTable from "@/app/(protected)/agents/components/agent-table";
import { buildGroupTree, type GroupNode } from "@/lib/groups";
import type { ViewMode } from "@/components/ui/view-toggle";
import * as agentsApi from "@/lib/api/resources/agents";
import { useAgentsStore } from "@/stores/agents-store";

type View = "available" | "all" | "archived";

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
}: {
	agents: Agent[];
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
}) {
	return (
		<div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
			{agents.map((agent, index) => (
				<div
					key={agent.id}
					className="h-full animate-in fade-in slide-in-from-bottom-3 duration-400"
					style={{
						animationDelay: `${index * 40}ms`,
						animationFillMode: "both",
					}}
				>
					<AgentCard agent={agent} archived={archived} onRemoved={onRemoved} />
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
}: {
	node: GroupNode<Agent>;
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
	storageKey: string;
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
	onClearSearch?: () => void;
	onCreateAgent?: () => void;
}

export default function AgentList({
	view,
	mode,
	search,
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
	const [archivedAgents, setArchivedAgents] = useState<Agent[]>([]);
	// The parent keys AgentList by active/archived, so entering the Archived
	// view mounts a fresh instance: this starts true and flips false once the
	// fetch resolves (the pre-store behavior, unchanged).
	const [archivedLoading, setArchivedLoading] = useState(true);

	useEffect(() => {
		if (!archived) {
			fetchAgents().catch(console.error);
			return;
		}
		agentsApi
			.listArchivedAgents()
			.then((agents) => {
				setArchivedAgents(agents);
			})
			.catch(console.error)
			.finally(() => {
				setArchivedLoading(false);
			});
	}, [archived, fetchAgents]);

	const agents = archived ? archivedAgents : storeAgents;
	const isLoading = archived ? archivedLoading : !storeReady;

	const handleRemoved = (agentId: string) => {
		if (archived) {
			// The store action (restore / permanent delete) already reconciled the
			// live list; only this page-local archived list needs the row gone.
			setArchivedAgents((prev) => prev.filter((a) => a.id !== agentId));
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

	// "Available to you" narrows to agents the user can actually use; "All" and
	// "Archived" show everything the fetch returned.
	const visible = useMemo(
		() =>
			view === "available"
				? matches.filter((a) => a.currentUserPermission)
				: matches,
		[matches, view],
	);

	const groupTree = useMemo(() => buildGroupTree(visible), [visible]);

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

	// "Available to you" is empty even though the workspace has agents.
	if (view === "available" && visible.length === 0) {
		return (
			<EmptyState
				icon={<Users className="size-[22px] text-[#4CA882]" />}
				title="Nothing shared with you yet"
				subtitle="Ask a workspace admin or an agent's owner to give you access, or switch to All to browse everything in your workspace."
			/>
		);
	}

	if (mode === "table") {
		// min-h-0 flex chain: lets the table body cap at the remaining page
		// height (WorkspacePage fillHeight) and scroll internally.
		return (
			<div className="flex min-h-0 w-full flex-1 flex-col animate-in fade-in duration-300">
				<AgentTable
					agents={visible}
					archived={archived}
					onRemoved={handleRemoved}
				/>
			</div>
		);
	}

	return (
		<div className="w-full animate-in fade-in duration-300">
			{groupTree.groups.map((group) => (
				<AgentSection
					key={`${view}:${group.path}`}
					node={group}
					archived={archived}
					onRemoved={handleRemoved}
					storageKey={`agents:group:${view}:${group.path}:expanded`}
				/>
			))}
			{groupTree.ungrouped.length > 0 &&
				(groupTree.groups.length > 0 ? (
					<AgentSection
						node={{
							name: "Others",
							path: "__ungrouped__",
							depth: 0,
							items: groupTree.ungrouped,
							children: [],
							count: groupTree.ungrouped.length,
						}}
						archived={archived}
						onRemoved={handleRemoved}
						storageKey={`agents:group:${view}:__ungrouped__:expanded`}
					/>
				) : (
					<AgentCardGrid
						agents={groupTree.ungrouped}
						archived={archived}
						onRemoved={handleRemoved}
					/>
				))}
		</div>
	);
}

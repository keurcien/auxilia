"use client";

import { useState, useEffect, useMemo } from "react";
import { Archive, ArrowRight, Plus, Search, Users, Zap } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import { api } from "@/lib/api/client";

type View = "available" | "all" | "archived";

// Agents with no tag are collected under this trailing pseudo-group.
const NO_TAG_ID = "__none__";

// How many cards a section shows before "See all" reveals the rest. The 8th
// grid cell holds an inline "See all" tile, so a collapsed section fills two
// clean rows on the 4-column grid.
const SECTION_CAP = 7;

interface AgentGroup {
	id: string;
	label: string;
	items: Agent[];
}

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

function AgentSection({
	label,
	agents,
	archived,
	onRemoved,
	storageKey,
}: {
	label: string;
	agents: Agent[];
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
	storageKey: string;
}) {
	// Sections only mount client-side, after AgentList's fetch resolves (it
	// renders null while loading), so reading localStorage in the initializer is
	// safe — there's no server render to mismatch against.
	const [expanded, setExpanded] = useState(() => {
		try {
			return localStorage.getItem(storageKey) === "1";
		} catch {
			// localStorage unavailable (e.g. private mode) — default to collapsed.
			return false;
		}
	});

	const toggle = () => {
		setExpanded((v) => {
			const next = !v;
			try {
				localStorage.setItem(storageKey, next ? "1" : "0");
			} catch {
				// Ignore persistence failures; the toggle still works in-session.
			}
			return next;
		});
	};

	const hasMore = agents.length > SECTION_CAP;
	const shown = expanded ? agents : agents.slice(0, SECTION_CAP);

	return (
		<section className="mb-10 last:mb-0 animate-in fade-in duration-300">
			<div className="flex items-center gap-3 mb-5">
				<h2 className="font-[family-name:var(--font-jakarta-sans)] text-[15px] font-bold tracking-[-0.01em] text-[#1E2D28] dark:text-foreground whitespace-nowrap">
					{label}
				</h2>
				<span className="font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#B8C8C0] dark:text-muted-foreground">
					{agents.length}
				</span>
				<div className="flex-1 h-px bg-[#E8EFE9] dark:bg-white/10" />
				{hasMore && expanded && (
					<button
						onClick={toggle}
						className="flex items-center gap-1 font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#8FA89E] dark:text-muted-foreground whitespace-nowrap cursor-pointer transition-colors hover:text-[#1E2D28] dark:hover:text-foreground"
					>
						Show less
						<ArrowRight className="size-3.5 -rotate-90" />
					</button>
				)}
			</div>

			<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
				{shown.map((agent, i) => (
					<div
						key={agent.id}
						className="h-full animate-in fade-in slide-in-from-bottom-3 duration-400"
						style={{ animationDelay: `${i * 40}ms`, animationFillMode: "both" }}
					>
						<AgentCard agent={agent} archived={archived} onRemoved={onRemoved} />
					</div>
				))}
				{hasMore && !expanded && (
					<button
						onClick={toggle}
						className="group flex h-full min-h-[120px] flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-[#cfe0d8] dark:border-white/15 bg-transparent text-[#8FA89E] dark:text-muted-foreground transition-colors duration-[130ms] ease-out cursor-pointer hover:border-[#4CA882] hover:text-[#1E2D28] dark:hover:border-[#4CA882] dark:hover:text-foreground"
					>
						<span className="flex items-center gap-1 font-[family-name:var(--font-jakarta-sans)] text-[14px] font-bold tracking-[-0.01em]">
							See all
							<ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
						</span>
						<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px] font-medium">
							+{agents.length - SECTION_CAP} more
						</span>
					</button>
				)}
			</div>
		</section>
	);
}

interface AgentListProps {
	view: View;
	search: string;
	onClearSearch?: () => void;
	onCreateAgent?: () => void;
}

export default function AgentList({
	view,
	search,
	onClearSearch,
	onCreateAgent,
}: AgentListProps) {
	const archived = view === "archived";
	const [agents, setAgents] = useState<Agent[]>([]);
	const [isLoading, setIsLoading] = useState(true);

	useEffect(() => {
		api
			.get<Agent[]>(archived ? "/agents?archived=true" : "/agents")
			.then((response) => {
				setAgents(response.data);
			})
			.catch(console.error)
			.finally(() => {
				setIsLoading(false);
			});
	}, [archived]);

	const handleRemoved = (agentId: string) => {
		setAgents((prev) => prev.filter((a) => a.id !== agentId));
	};

	const matches = useMemo(() => {
		if (!search) return agents;
		const query = search.toLowerCase();
		return agents.filter((agent) => agent.name.toLowerCase().includes(query));
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

	// Group by tag (each agent has at most one, so every agent appears exactly
	// once). Untagged agents fall into the trailing "Others" group. Tags are
	// sorted alphabetically to match the backend ordering.
	const groups = useMemo<AgentGroup[]>(() => {
		const byTag = new Map<string, AgentGroup>();
		const untagged: Agent[] = [];
		for (const agent of visible) {
			const tag = agent.tag;
			if (!tag) {
				untagged.push(agent);
				continue;
			}
			const existing = byTag.get(tag.id);
			if (existing) {
				existing.items.push(agent);
			} else {
				byTag.set(tag.id, {
					id: tag.id,
					label: tag.name,
					items: [agent],
				});
			}
		}
		const ordered = [...byTag.values()].sort((a, b) =>
			a.label.localeCompare(b.label),
		);
		if (untagged.length > 0) {
			ordered.push({
				id: NO_TAG_ID,
				label: "Others",
				items: untagged,
			});
		}
		return ordered;
	}, [visible]);

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
				subtitle="Ask a workspace admin or an agent's owner to give you access — or switch to All to browse everything in your workspace."
			/>
		);
	}

	return (
		<div className="w-full animate-in fade-in duration-300">
			{groups.map((group) => (
				<AgentSection
					// Key by view too: the expanded state is read from localStorage in
					// a useState initializer, so the section must remount when the
					// view (and thus its storage key) changes.
					key={`${view}:${group.id}`}
					label={group.label}
					agents={group.items}
					archived={archived}
					onRemoved={handleRemoved}
					storageKey={`agents:section:${view}:${group.id}:expanded`}
				/>
			))}
		</div>
	);
}

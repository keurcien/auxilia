"use client";

import { useState, useEffect, useMemo } from "react";
import { ArrowRight, Info, Plus, Search, Zap } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import { api } from "@/lib/api/client";

// Stacked sections, top to bottom. "Discover" (agents not shared with the
// user) only renders when it actually has agents, so the common view stays
// "yours + shared", matching the page's description.
const GROUPS = [
	{
		key: "mine",
		label: "Your agents",
		filter: (a: Agent) => a.currentUserPermission === "owner",
	},
	{
		key: "shared",
		label: "Shared with you",
		filter: (a: Agent) =>
			a.currentUserPermission === "admin" ||
			a.currentUserPermission === "editor" ||
			a.currentUserPermission === "member",
	},
	{
		key: "discover",
		label: "Discover",
		filter: (a: Agent) => !a.currentUserPermission,
	},
];

// How many cards a section shows before "See all" reveals the rest.
const SECTION_CAP = 6;

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
	note,
}: {
	label: string;
	agents: Agent[];
	note?: React.ReactNode;
}) {
	const [expanded, setExpanded] = useState(false);
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
				{hasMore && (
					<button
						onClick={() => {
						setExpanded((v) => !v);
					}}
						className="flex items-center gap-1 font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#8FA89E] dark:text-muted-foreground whitespace-nowrap cursor-pointer transition-colors hover:text-[#1E2D28] dark:hover:text-foreground"
					>
						{expanded ? "Show less" : "See all"}
						<ArrowRight className="size-3.5" />
					</button>
				)}
			</div>

			{note}

			<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
				{shown.map((agent, i) => (
					<div
						key={agent.id}
						className="h-full animate-in fade-in slide-in-from-bottom-3 duration-400"
						style={{ animationDelay: `${i * 40}ms`, animationFillMode: "both" }}
					>
						<AgentCard agent={agent} />
					</div>
				))}
			</div>
		</section>
	);
}

interface AgentListProps {
	search: string;
	onClearSearch?: () => void;
	onCreateAgent?: () => void;
}

export default function AgentList({
	search,
	onClearSearch,
	onCreateAgent,
}: AgentListProps) {
	const [agents, setAgents] = useState<Agent[]>([]);
	const [isLoading, setIsLoading] = useState(true);

	useEffect(() => {
		api
			.get<Agent[]>("/agents")
			.then((response) => setAgents(response.data))
			.catch(console.error)
			.finally(() => setIsLoading(false));
	}, []);

	const matches = useMemo(() => {
		if (!search) return agents;
		const query = search.toLowerCase();
		return agents.filter((agent) => agent.name.toLowerCase().includes(query));
	}, [agents, search]);

	const grouped = useMemo(
		() =>
			GROUPS.map((group) => ({
				...group,
				items: matches.filter(group.filter),
			})),
		[matches],
	);

	if (isLoading) return null;

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

	// Search returned nothing.
	if (search && matches.length === 0) {
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

	// "Your agents" / "Shared with you" always render so the page structure
	// stays consistent even at zero; "Discover" only appears when it has agents.
	// While searching, drop empty sections so only matches show.
	const sections = grouped.filter(
		(group) =>
			group.items.length > 0 || (!search && group.key !== "discover"),
	);

	return (
		<div className="w-full animate-in fade-in duration-300">
			{sections.map((group) => (
				<AgentSection
					key={group.key}
					label={group.label}
					agents={group.items}
					note={
						group.key === "discover" ? (
							<div className="flex items-center gap-2.5 px-4 py-3 mb-5 rounded-xl bg-primary/10 text-primary text-[13.5px]">
								<Info className="size-4 shrink-0" />
								These agents exist in your workspace but haven&apos;t been shared
								with you yet. Contact the owner to request access.
							</div>
						) : undefined
					}
				/>
			))}
		</div>
	);
}

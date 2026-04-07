"use client";

import { useState, useEffect, useMemo } from "react";
import { Compass, Info, Plus, Search, Users, Zap } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import { api } from "@/lib/api/client";
import { SearchBar } from "@/components/ui/search-bar";

const TABS = [
	{
		key: "mine",
		label: "My agents",
		filter: (a: Agent) => a.currentUserPermission === "owner",
	},
	{
		key: "shared",
		label: "Shared with me",
		filter: (a: Agent) =>
			a.currentUserPermission === "admin" ||
			a.currentUserPermission === "editor" ||
			a.currentUserPermission === "user",
	},
	{
		key: "discover",
		label: "Discover",
		filter: (a: Agent) => !a.currentUserPermission,
	},
];

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

interface AgentListProps {
	onCreateAgent?: () => void;
}

export default function AgentList({ onCreateAgent }: AgentListProps) {
	const [agents, setAgents] = useState<Agent[]>([]);
	const [activeTab, setActiveTab] = useState("mine");
	const [search, setSearch] = useState("");
	const [isLoading, setIsLoading] = useState(true);

	useEffect(() => {
		api
			.get<Agent[]>("/agents")
			.then((response) => setAgents(response.data))
			.catch(console.error)
			.finally(() => setIsLoading(false));
	}, []);

	const currentTab = TABS.find((t) => t.key === activeTab)!;

	const filtered = useMemo(() => {
		return agents.filter((agent) => {
			const matchesTab = currentTab.filter(agent);
			const matchesSearch =
				!search || agent.name.toLowerCase().includes(search.toLowerCase());
			return matchesTab && matchesSearch;
		});
	}, [agents, search, currentTab]);

	const tabCounts = useMemo(() => {
		return Object.fromEntries(
			TABS.map((tab) => [tab.key, agents.filter(tab.filter).length]),
		);
	}, [agents]);

	if (isLoading) return null;

	const renderEmptyState = () => {
		// Search with no results
		if (search) {
			return (
				<EmptyState
					icon={<Search className="size-[22px] text-[#4CA882]" />}
					title="No agents found"
					subtitle="Try adjusting your search or filters to find what you're looking for."
					action={{
						label: "Clear search",
						icon: <Search className="size-[15px] text-[#4CA882]" />,
						onClick: () => setSearch(""),
					}}
				/>
			);
		}

		// Empty workspace (no agents at all in "mine" tab)
		if (activeTab === "mine") {
			return (
				<EmptyState
					icon={<Zap className="size-[22px] text-[#4CA882]" />}
					title="Create your first agent"
					subtitle="Agents help your team automate tasks and access your data tools."
					action={onCreateAgent ? {
						label: "Create an agent",
						icon: <Plus className="size-[15px] text-[#4CA882]" />,
						onClick: onCreateAgent,
					} : undefined}
				/>
			);
		}

		if (activeTab === "shared") {
			return (
				<EmptyState
					icon={<Users className="size-[22px] text-[#4CA882]" />}
					title="Nothing shared yet"
					subtitle="When someone shares an agent with you, it will appear here."
				/>
			);
		}

		// Discover
		return (
			<EmptyState
				icon={<Compass className="size-[22px] text-[#4CA882]" />}
				title="Nothing to discover"
				subtitle="All workspace agents are already shared with you."
			/>
		);
	};

	return (
		<div className="w-full mx-auto animate-in fade-in duration-300">
			<div className="w-full flex items-center justify-between mb-7 overflow-x-auto">
				<div className="flex gap-1.5 bg-[#F5F8F6] dark:bg-white/5 rounded-full p-1">
					{TABS.map((tab) => {
						const isActive = activeTab === tab.key;
						return (
							<button
								key={tab.key}
								onClick={() => setActiveTab(tab.key)}
								className={`flex items-center gap-1.5 px-4.5 py-2 rounded-full text-[13.5px] font-[family-name:var(--font-dm-sans)] cursor-pointer transition-all whitespace-nowrap ${
									isActive
										? "bg-white dark:bg-white/10 text-[#1E2D28] dark:text-white font-semibold shadow-[0_1px_4px_rgba(0,0,0,0.06)]"
										: "bg-transparent text-[#8FA89E] dark:text-white/40 font-medium hover:text-[#6B7F76] dark:hover:text-white/60"
								}`}
							>
								{tab.label}
								<span
									className={`text-[11.5px] font-semibold px-1.5 py-0.5 rounded-full transition-colors ${
										isActive
											? "bg-[#EDF4F0] dark:bg-white/10 text-[#3D8B63] dark:text-emerald-400"
											: "text-[#B8C8C0] dark:text-white/30"
									}`}
								>
									{tabCounts[tab.key]}
								</span>
							</button>
						);
					})}
				</div>
				<SearchBar
					placeholder="Search agents..."
					value={search}
					onChange={setSearch}
					className="w-64 shrink-0"
				/>
			</div>

			{activeTab === "discover" && filtered.length > 0 && (
				<div className="flex items-center gap-2.5 px-4 py-3 mb-6 rounded-xl bg-primary/10 text-primary text-[13.5px]">
					<Info className="size-4 shrink-0" />
					These agents exist in your workspace but haven&apos;t been shared with
					you yet. Contact the owner to request access.
				</div>
			)}

			{filtered.length > 0 ? (
				<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
					{filtered.map((agent, i) => (
						<div
							key={agent.id}
							className="h-full animate-in fade-in slide-in-from-bottom-3 duration-400"
							style={{ animationDelay: `${i * 50}ms`, animationFillMode: "both" }}
						>
							<AgentCard agent={agent} />
						</div>
					))}
				</div>
			) : (
				renderEmptyState()
			)}
		</div>
	);
}

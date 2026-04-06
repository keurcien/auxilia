"use client";

import { useState, useEffect, useMemo } from "react";
import { Info } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import { api } from "@/lib/api/client";
import { SearchBar } from "@/components/ui/search-bar";

const TABS = [
	{
		key: "mine",
		label: "My agents",
		filter: (a: Agent) => a.currentUserPermission === "owner",
		emptyTitle: "No agents yet",
		emptyDesc: "Create your first agent to get started.",
	},
	{
		key: "shared",
		label: "Shared with me",
		filter: (a: Agent) =>
			a.currentUserPermission === "admin" ||
			a.currentUserPermission === "editor" ||
			a.currentUserPermission === "user",
		emptyTitle: "Nothing shared yet",
		emptyDesc: "When collaborators share agents with you, they'll appear here.",
	},
	{
		key: "discover",
		label: "Discover",
		filter: (a: Agent) => !a.currentUserPermission,
		emptyTitle: "Nothing to discover",
		emptyDesc: "All workspace agents are already shared with you.",
	},
];

export default function AgentList() {
	const [agents, setAgents] = useState<Agent[]>([]);
	const [activeTab, setActiveTab] = useState("mine");
	const [search, setSearch] = useState("");

	useEffect(() => {
		api
			.get<Agent[]>("/agents")
			.then((response) => setAgents(response.data))
			.catch(console.error);
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

	if (agents.length === 0) {
		return (
			<div className="flex items-center justify-center p-12 border border-border rounded-lg">
				<div className="text-muted-foreground">
					No agents configured. Click the &quot;Create an agent&quot; button to
					get started.
				</div>
			</div>
		);
	}

	return (
		<div className="w-full mx-auto">
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
					{filtered.map((agent) => (
						<AgentCard key={agent.id} agent={agent} />
					))}
				</div>
			) : search ? (
				<div className="text-center py-20 text-muted-foreground text-sm">
					No agents found matching &quot;{search}&quot;
				</div>
			) : (
				<div className="flex flex-col items-center justify-center py-16 px-5 rounded-2xl border border-dashed border-border bg-card">
					<div className="text-[15px] font-semibold text-foreground mb-1.5">
						{currentTab.emptyTitle}
					</div>
					<div className="text-[13.5px] text-muted-foreground max-w-[300px] text-center">
						{currentTab.emptyDesc}
					</div>
				</div>
			)}
		</div>
	);
}

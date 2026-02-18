"use client";

import { useState, useEffect, useMemo } from "react";
import { Info, Search } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import { api } from "@/lib/api/client";
import { Input } from "@/components/ui/input";

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
			<div className="flex items-center justify-between mb-7">
				<div className="flex border-b border-border">
					{TABS.map((tab) => {
						const isActive = activeTab === tab.key;
						return (
							<button
								key={tab.key}
								onClick={() => setActiveTab(tab.key)}
								className={`relative flex items-center gap-2 px-5 pb-3 pt-2.5 text-sm cursor-pointer transition-colors whitespace-nowrap ${
									isActive
										? "text-foreground font-semibold"
										: "text-muted-foreground font-normal hover:text-foreground/70"
								}`}
							>
								{tab.label}
								<span
									className={`text-[11.5px] font-semibold px-2 py-0.5 rounded-full transition-colors ${
										isActive
											? "bg-primary/10 text-primary"
											: "bg-muted text-muted-foreground"
									}`}
								>
									{tabCounts[tab.key]}
								</span>
								{isActive && (
									<div className="absolute bottom-[-1.5px] left-3 right-3 h-0.5 rounded-full bg-primary" />
								)}
							</button>
						);
					})}
				</div>
				<div className="relative w-64">
					<Search className="absolute left-3.5 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
					<Input
						placeholder="Search agents..."
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						className="pl-10"
					/>
				</div>
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

import { useState } from "react";
import { useRouter } from "next/navigation";

import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogTitle,
} from "@/components/ui/dialog";
import { SearchBar } from "@/components/ui/search-bar";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import type { Agent } from "@/types/agents";
import { useAgentsStore } from "@/stores/agents-store";

interface SelectAgentDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onAgentSelect?: (agent: Agent) => void;
}

export function SelectAgentDialog({
	open,
	onOpenChange,
	onAgentSelect,
}: SelectAgentDialogProps) {
	const router = useRouter();
	const [searchQuery, setSearchQuery] = useState("");
	const agents = useAgentsStore((state) => state.agents);

	const handleSelectAgent = (agent: Agent) => {
		onAgentSelect?.(agent);
		onOpenChange(false);
		router.push(`/agents/${agent.id}/chat`);
	};

	const filteredAgents = agents
		.filter((agent) => agent.currentUserPermission !== null)
		.filter((agent) =>
			agent.name.toLowerCase().includes(searchQuery.toLowerCase()),
		);

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="gap-0 p-0">
				{/* Header */}
				<div className="px-6 pt-6">
					<DialogTitle>Chat with an agent</DialogTitle>
					<DialogDescription className="mt-1.5">
						Select an agent to start a conversation
					</DialogDescription>
				</div>

				{/* Search */}
				<div className="px-6 pt-4 pb-1">
					<SearchBar
						placeholder="Search for an agent..."
						value={searchQuery}
						onChange={setSearchQuery}
					/>
				</div>

				{/* Agent list */}
				<div className="px-3 pt-2 pb-4 max-h-[340px] overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{filteredAgents.map((agent) => (
						<div
							key={agent.id}
							className="flex items-center gap-3.5 px-3 py-2.5 rounded-[8px] hover:bg-hover dark:hover:bg-white/5 cursor-pointer transition-colors group"
							onClick={() => { handleSelectAgent(agent); }}
						>
							<AgentAvatar
								color={agent.color}
								emoji={agent.emoji}
								size="md"
								className="transition-transform duration-300 group-hover:scale-105"
							/>
							<span className="text-[13.5px] font-semibold text-ink dark:text-panel-button truncate">
								{agent.name}
							</span>
						</div>
					))}
					{filteredAgents.length === 0 && (
						<p className="text-center text-[13px] text-meta dark:text-panel-dim font-medium py-8">
							No agents found.
						</p>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}

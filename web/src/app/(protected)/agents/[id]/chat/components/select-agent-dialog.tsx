import { useState } from "react";
import { useRouter } from "next/navigation";

import {
	Dialog,
	DialogContent,
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
			<DialogContent
				className="sm:max-w-[440px] rounded-[28px] p-0 gap-0 overflow-hidden"
				showCloseButton={false}
			>
				{/* Header */}
				<div className="px-8 pt-7 pb-0">
					<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[22px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
						Chat with an Agent
					</DialogTitle>
					<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-1">
						Select an agent to start a conversation
					</p>
				</div>

				{/* Search */}
				<div className="px-8 pt-5 pb-1">
					<SearchBar
						placeholder="Search for an agent..."
						value={searchQuery}
						onChange={setSearchQuery}
					/>
				</div>

				{/* Agent list */}
				<div className="px-5 pt-3 pb-6 max-h-[340px] overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{filteredAgents.map((agent) => (
						<div
							key={agent.id}
							className="flex items-center gap-3.5 px-3 py-2.5 rounded-[16px] hover:bg-[#F8FAF9] dark:hover:bg-white/5 cursor-pointer transition-all duration-200 group"
							onClick={() => handleSelectAgent(agent)}
						>
							<AgentAvatar
								color={agent.color}
								emoji={agent.emoji}
								size="md"
								className="transition-transform duration-300 group-hover:scale-105"
							/>
							<span className="font-[family-name:var(--font-dm-sans)] text-[14.5px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
								{agent.name}
							</span>
						</div>
					))}
					{filteredAgents.length === 0 && (
						<p className="font-[family-name:var(--font-dm-sans)] text-center text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium py-8">
							No agents found.
						</p>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}

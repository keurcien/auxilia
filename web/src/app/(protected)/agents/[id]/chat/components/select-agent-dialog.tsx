import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
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
			<DialogContent className="sm:max-w-[425px] gap-2">
				<DialogHeader>
					<DialogTitle>Chat with an Agent</DialogTitle>
				</DialogHeader>

				<div className="relative my-2">
					<Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
					<Input
						placeholder="Search for an agent..."
						className="pl-9"
						value={searchQuery}
						onChange={(e) => setSearchQuery(e.target.value)}
					/>
				</div>

				<div className="grid gap-2 mt-2 max-h-[300px] overflow-y-auto">
					{filteredAgents.map((agent) => (
						<div
							key={agent.id}
							className="flex items-center gap-3 p-2 rounded-lg hover:bg-muted cursor-pointer transition-colors border border-transparent hover:border-border"
							onClick={() => handleSelectAgent(agent)}
						>
							<span className="text-2xl">{agent.emoji || "🤖"}</span>
							<span className="font-medium text-sm">{agent.name}</span>
						</div>
					))}
					{filteredAgents.length === 0 && (
						<p className="text-center text-sm text-muted-foreground py-4">
							No agents found.
						</p>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}

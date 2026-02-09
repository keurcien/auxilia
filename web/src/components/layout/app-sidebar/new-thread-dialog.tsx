import { useEffect, useState } from "react";
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
import { api } from "@/lib/api/client";

interface NewThreadDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

export function NewThreadDialog({ open, onOpenChange }: NewThreadDialogProps) {
	const router = useRouter();
	const [searchQuery, setSearchQuery] = useState("");
	const [agents, setAgents] = useState<Agent[]>([]);

	useEffect(() => {
		if (open) {
			api
				.get(`/agents`)
				.then((res) => res.data)
				.then((data) => {
					setAgents(data);
				});
			setTimeout(() => {
				setSearchQuery("");
			}, 0);
		}
	}, [open]);

	const handleSelectAgent = (agentId: string) => {
		onOpenChange(false);
		router.push(`/agents/${agentId}/chat`);
	};

	const filteredAgents = agents.filter((agent) =>
		agent.name.toLowerCase().includes(searchQuery.toLowerCase())
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
							onClick={() => handleSelectAgent(agent.id)}
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

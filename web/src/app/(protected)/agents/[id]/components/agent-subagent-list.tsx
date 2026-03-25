"use client";

import { useState } from "react";
import { Plus, X, Info } from "lucide-react";
import { Agent } from "@/types/agents";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";
import AddAgentSubagentDialog from "./add-agent-subagent-dialog";

interface AgentSubagentListProps {
	agent: Agent;
	onSaving?: () => void;
	onSaved?: () => void;
}

export default function AgentSubagentList({
	agent: initialAgent,
	onSaving,
	onSaved,
}: AgentSubagentListProps) {
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const [agent, setAgent] = useState<Agent>(initialAgent);
	const [dialogOpen, setDialogOpen] = useState(false);
	const [removingId, setRemovingId] = useState<string | null>(null);

	const refreshAgent = async (affectedSubagentId?: string) => {
		const [coordRes] = await Promise.all([
			api.get(`/agents/${agent.id}`),
			// Also refresh the affected subagent so its isSubagent flag updates in the store
			...(affectedSubagentId
				? [
						api.get(`/agents/${affectedSubagentId}`).then((res) => {
							updateAgent(affectedSubagentId, res.data);
						}),
					]
				: []),
		]);
		setAgent(coordRes.data);
		updateAgent(agent.id, coordRes.data);
	};

	const handleRemove = async (subagentId: string) => {
		setRemovingId(subagentId);
		onSaving?.();
		try {
			await api.delete(`/agents/${agent.id}/subagents/${subagentId}`);
			await refreshAgent(subagentId);
			onSaved?.();
		} catch (error) {
			console.error("Failed to remove subagent:", error);
			onSaved?.();
		} finally {
			setRemovingId(null);
		}
	};

	// If this agent is used as a subagent elsewhere, show info banner instead
	if (agent.isSubagent) {
		return (
			<div className="flex flex-col mt-4">
				<h2 className="text-muted-foreground text-sm leading-5 font-medium mb-2">
					Subagents
				</h2>
				<div className="flex items-start gap-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/40 p-3">
					<Info className="w-4 h-4 text-gray-400 dark:text-gray-500 mt-0.5 shrink-0" />
					<p className="text-sm text-gray-600 dark:text-gray-400">
						This agent is already used as a subagent, it cannot have subagents.
					</p>
				</div>
			</div>
		);
	}

	return (
		<div className="flex flex-col mt-4">
			<div className="flex items-center justify-between mb-2 shrink-0">
				<h2 className="text-muted-foreground text-sm leading-5 font-medium">
					Subagents
				</h2>
				<Button
					variant="ghost"
					size="sm"
					className="cursor-pointer"
					onClick={() => setDialogOpen(true)}
				>
					<Plus className="w-4 h-4 mr-1" />
					Add Subagent
				</Button>
			</div>
			<div className="rounded-lg border min-h-0">
				{agent.subagents && agent.subagents.length > 0 ? (
					agent.subagents.map((sub) => (
						<div
							key={sub.id}
							className="flex items-center justify-between px-4 py-3 border-b last:border-b-0"
						>
							<div className="flex items-center gap-3 min-w-0">
								<span className="text-xl shrink-0">{sub.emoji || "🤖"}</span>
								<div className="min-w-0">
									<p className="text-sm font-medium truncate">{sub.name}</p>
									{sub.description && (
										<p className="text-xs text-muted-foreground truncate">
											{sub.description}
										</p>
									)}
								</div>
							</div>
							<Button
								variant="ghost"
								size="icon"
								className="cursor-pointer shrink-0"
								onClick={() => handleRemove(sub.id)}
								disabled={removingId === sub.id}
							>
								<X className="w-4 h-4" />
							</Button>
						</div>
					))
				) : (
					<div className="p-4 text-sm text-muted-foreground text-center">
						No subagents configured
					</div>
				)}
			</div>

			<AddAgentSubagentDialog
				open={dialogOpen}
				onOpenChange={setDialogOpen}
				agent={agent}
				onSubagentAdded={(subagentId) => refreshAgent(subagentId)}
				onSaving={onSaving}
				onSaved={onSaved}
			/>
		</div>
	);
}

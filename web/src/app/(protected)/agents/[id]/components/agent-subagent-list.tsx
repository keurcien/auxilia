"use client";

import { useState } from "react";
import { Plus, X, Info } from "lucide-react";
import { Agent } from "@/types/agents";
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
			<div className="flex flex-col mt-8">
				<span className="text-[10.5px] font-bold text-[#94a59d] dark:text-muted-foreground uppercase tracking-[0.12em] font-[family-name:var(--font-dm-sans)] mb-2.5">
					Subagents
				</span>
				<div className="flex items-start gap-2.5 rounded-[12px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)] px-4 py-3.5">
					<Info className="w-4 h-4 text-[#94a59d] mt-0.5 shrink-0" />
					<p className="font-[family-name:var(--font-dm-sans)] text-[12.5px] text-[#5f7068] dark:text-muted-foreground">
						This agent is already used as a subagent, it cannot have subagents.
					</p>
				</div>
			</div>
		);
	}

	return (
		<div className="flex flex-col mt-8">
			<div className="flex items-center justify-between mb-3.5 shrink-0">
				<span className="text-[10.5px] font-bold text-[#94a59d] dark:text-muted-foreground uppercase tracking-[0.12em] font-[family-name:var(--font-dm-sans)]">
					Subagents
				</span>
				<button
					className="flex items-center gap-1.5 px-[13px] py-1.5 rounded-[9px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.05)] font-[family-name:var(--font-dm-sans)] text-[12px] font-medium normal-case tracking-normal text-[#1e2d28] dark:text-foreground cursor-pointer transition-colors hover:border-[#A3B5AD]"
					onClick={() => setDialogOpen(true)}
				>
					<Plus className="w-3 h-3 text-[#6b7f76] dark:text-muted-foreground" />
					Add subagent
				</button>
			</div>
			<div className="rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)] overflow-hidden min-h-0">
				{agent.subagents && agent.subagents.length > 0 ? (
					agent.subagents.map((sub, i) => (
						<div
							key={sub.id}
							className={`group flex items-center px-4.5 py-3.5 cursor-default transition-colors hover:bg-[#F8FAF9] dark:hover:bg-white/5 ${
								i < agent.subagents!.length - 1 ? "border-b border-[#F0F3F2] dark:border-white/5" : ""
							}`}
						>
							<div
								style={{
									background: sub.color ? `linear-gradient(145deg, ${sub.color}14, ${sub.color}10)` : "linear-gradient(145deg, #9E9E9E14, #75757510)",
									border: sub.color ? `1.5px solid ${sub.color}18` : "1.5px solid #9E9E9E18",
								}}
								className="shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-[16px] mr-3"
							>
								{sub.emoji || "🤖"}
							</div>
							<span className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground flex-1 truncate">
								{sub.name}
							</span>
							<button
								className="w-[30px] h-[30px] rounded-full flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all hover:bg-[#F0F3F2] dark:hover:bg-white/10 cursor-pointer"
								onClick={() => handleRemove(sub.id)}
								disabled={removingId === sub.id}
							>
								<X className="w-[14px] h-[14px] text-[#A3B5AD]" />
							</button>
						</div>
					))
				) : (
					<div className="p-4 font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground text-center">
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

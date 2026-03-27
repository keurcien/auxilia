"use client";

import { useState, useMemo } from "react";
import { Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { Agent } from "@/types/agents";
import { useAgentsStore } from "@/stores/agents-store";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface AddAgentSubagentDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agent: Agent;
	onSubagentAdded?: (subagentId: string) => void;
	onSaving?: () => void;
	onSaved?: () => void;
}

interface AgentCandidateCardProps {
	candidate: Agent;
	coordinatorId: string;
	onAdd: (subagentId: string) => void;
	disabled: boolean;
	disabledReason?: string;
	onSaving?: () => void;
	onSaved?: () => void;
}

function AgentCandidateCard({
	candidate,
	coordinatorId,
	onAdd,
	disabled,
	disabledReason,
	onSaving,
	onSaved,
}: AgentCandidateCardProps) {
	const [isAdding, setIsAdding] = useState(false);

	const handleAdd = async () => {
		setIsAdding(true);
		onSaving?.();
		try {
			await api.post(
				`/agents/${coordinatorId}/subagents/${candidate.id}`,
				{},
			);
			onAdd(candidate.id);
			onSaved?.();
		} catch (error) {
			console.error("Failed to add subagent:", error);
			onSaved?.();
		} finally {
			setIsAdding(false);
		}
	};

	return (
		<div
			className={`flex items-center justify-between px-4 py-3 rounded-md border ${
				disabled ? "opacity-50" : ""
			}`}
		>
			<div className="flex items-center gap-3 min-w-0 flex-1">
				<span className="text-xl shrink-0">
					{candidate.emoji || "🤖"}
				</span>
				<div className="min-w-0 flex-1">
					<p className="text-sm font-medium truncate">{candidate.name}</p>
					{disabled && disabledReason ? (
						<p className="text-xs text-muted-foreground truncate">
							{disabledReason}
						</p>
					) : (
						candidate.description && (
							<p className="text-xs text-muted-foreground truncate">
								{candidate.description}
							</p>
						)
					)}
				</div>
			</div>
			<Button
				variant="ghost"
				size="icon"
				className="cursor-pointer shrink-0"
				onClick={handleAdd}
				disabled={disabled || isAdding}
			>
				<Plus className="w-4 h-4" />
			</Button>
		</div>
	);
}

export default function AddAgentSubagentDialog({
	open,
	onOpenChange,
	agent,
	onSubagentAdded,
	onSaving,
	onSaved,
}: AddAgentSubagentDialogProps) {
	const allAgents = useAgentsStore((state) => state.agents);

	const alreadyBoundIds = useMemo(
		() => new Set(agent.subagents?.map((s) => s.id) || []),
		[agent.subagents],
	);

	// Candidates: all agents except self, already-bound, and archived
	const candidates = useMemo(() => {
		return allAgents
			.filter((a) => a.id !== agent.id && !alreadyBoundIds.has(a.id))
			.map((a) => {
				let disabled = false;
				let disabledReason: string | undefined;

				if (a.subagents && a.subagents.length > 0) {
					disabled = true;
					disabledReason = "Has subagents of its own";
				} else if (a.isSubagent) {
					disabled = true;
					disabledReason = "Already used as a subagent";
				}

				return { agent: a, disabled, disabledReason };
			})
			.sort((a, b) => {
				// Eligible agents first
				if (a.disabled !== b.disabled) return a.disabled ? 1 : -1;
				return a.agent.name.localeCompare(b.agent.name);
			});
	}, [allAgents, agent.id, alreadyBoundIds]);

	const handleSubagentAdded = (subagentId: string) => {
		onSubagentAdded?.(subagentId);
		// Close if no more eligible candidates
		const eligibleCount = candidates.filter((c) => !c.disabled).length;
		if (eligibleCount <= 1) {
			onOpenChange(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[600px] max-h-[600px]">
				<DialogHeader>
					<DialogTitle>Add Subagent</DialogTitle>
				</DialogHeader>
				<div className="py-4 overflow-y-auto">
					{candidates.length > 0 ? (
						<div className="max-h-[400px] flex flex-col gap-2 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							{candidates.map(({ agent: candidate, disabled, disabledReason }) => (
								<AgentCandidateCard
									key={candidate.id}
									candidate={candidate}
									coordinatorId={agent.id}
									onAdd={handleSubagentAdded}
									disabled={disabled}
									disabledReason={disabledReason}
									onSaving={onSaving}
									onSaved={onSaved}
								/>
							))}
						</div>
					) : (
						<div className="text-center py-8 text-muted-foreground">
							<p className="text-sm">
								No agents available to add as subagents.
							</p>
						</div>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}

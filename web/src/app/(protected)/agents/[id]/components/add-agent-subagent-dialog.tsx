"use client";

import { useMemo } from "react";
import { Plus } from "lucide-react";
import { Agent, SubagentInfo } from "@/types/agents";
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
	agentId: string;
	boundSubagentIds: string[];
	onAdd: (subagent: SubagentInfo) => void;
}

interface AgentCandidateCardProps {
	candidate: Agent;
	onAdd: (subagent: SubagentInfo) => void;
	disabled: boolean;
	disabledReason?: string;
}

function AgentCandidateCard({
	candidate,
	onAdd,
	disabled,
	disabledReason,
}: AgentCandidateCardProps) {
	const handleAdd = () => {
		onAdd({
			id: candidate.id,
			name: candidate.name,
			emoji: candidate.emoji,
			color: candidate.color,
			description: candidate.description,
		});
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
				disabled={disabled}
			>
				<Plus className="w-4 h-4" />
			</Button>
		</div>
	);
}

export default function AddAgentSubagentDialog({
	open,
	onOpenChange,
	agentId,
	boundSubagentIds,
	onAdd,
}: AddAgentSubagentDialogProps) {
	const allAgents = useAgentsStore((state) => state.agents);

	const alreadyBoundIds = useMemo(
		() => new Set(boundSubagentIds),
		[boundSubagentIds],
	);

	// Candidates: all agents except self, already-bound, and archived
	const candidates = useMemo(() => {
		return allAgents
			.filter((a) => a.id !== agentId && !alreadyBoundIds.has(a.id))
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
	}, [allAgents, agentId, alreadyBoundIds]);

	const handleAdd = (subagent: SubagentInfo) => {
		onAdd(subagent);
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
									onAdd={handleAdd}
									disabled={disabled}
									disabledReason={disabledReason}
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

"use client";

import { useState, useMemo } from "react";
import { Plus } from "lucide-react";
import { Agent } from "@/types/agents";
import { useAgentsStore } from "@/stores/agents-store";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { SearchBar } from "@/components/ui/search-bar";

interface AddAgentSubagentDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	supervisorId: string;
	/** Subagents already attached in the draft. */
	currentSubagentIds: string[];
	/** Draft update: attach a subagent. */
	onAdd: (subagentId: string) => void;
}

interface AgentCandidateCardProps {
	candidate: Agent;
	onAdd: (subagentId: string) => void;
	disabled: boolean;
	disabledReason?: string;
}

function AgentCandidateCard({
	candidate,
	onAdd,
	disabled,
	disabledReason,
}: AgentCandidateCardProps) {
	return (
		<div
			className={`flex items-center justify-between rounded-[10px] border border-hairline bg-canvas px-4 py-3 transition-colors dark:bg-white/5 ${
				disabled ? "opacity-50" : "hover:bg-sidebar dark:hover:bg-white/10"
			}`}
		>
			<div className="flex items-center gap-3 min-w-0 flex-1">
				<span className="text-xl shrink-0">
					{candidate.emoji || "🤖"}
				</span>
				<div className="min-w-0 flex-1">
					<p className="truncate text-[13.5px] font-semibold text-ink dark:text-panel-button">
						{candidate.name}
					</p>
					{disabled && disabledReason ? (
						<p className="truncate text-[12px] text-label dark:text-panel-dim">
							{disabledReason}
						</p>
					) : (
						candidate.description && (
							<p className="truncate text-[12px] text-label dark:text-panel-dim">
								{candidate.description}
							</p>
						)
					)}
				</div>
			</div>
			<button
				type="button"
				className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] border border-input text-label outline-none transition-colors hover:border-border-hover hover:text-ink focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none dark:border-white/10 dark:hover:bg-white/10 dark:hover:text-panel-button"
				onClick={() => {
					onAdd(candidate.id);
				}}
				disabled={disabled}
				aria-label={`Add ${candidate.name}`}
			>
				<Plus className="size-3.5" />
			</button>
		</div>
	);
}

export default function AddAgentSubagentDialog({
	open,
	onOpenChange,
	supervisorId,
	currentSubagentIds,
	onAdd,
}: AddAgentSubagentDialogProps) {
	const allAgents = useAgentsStore((state) => state.agents);
	const [search, setSearch] = useState("");

	const alreadyBoundIds = useMemo(
		() => new Set(currentSubagentIds),
		[currentSubagentIds],
	);

	// All addable candidates: every agent except self and already-bound.
	// Not search-filtered, so eligibility counts reflect the full set.
	const allCandidates = useMemo(() => {
		return allAgents
			.filter((a) => a.id !== supervisorId && !alreadyBoundIds.has(a.id))
			.map((a) => {
				// One nesting level max: an agent with its own subagents can't be
				// a subagent. Being a subagent of ANOTHER supervisor is fine —
				// subagents are shared, not exclusive.
				const disabled = Boolean(a.subagents && a.subagents.length > 0);
				return {
					agent: a,
					disabled,
					disabledReason: disabled ? "Has subagents of its own" : undefined,
				};
			})
			.sort((a, b) => {
				// Eligible agents first
				if (a.disabled !== b.disabled) return a.disabled ? 1 : -1;
				return a.agent.name.localeCompare(b.agent.name);
			});
	}, [allAgents, supervisorId, alreadyBoundIds]);

	// Display list, narrowed by the search term (display only).
	const candidates = useMemo(() => {
		const term = search.toLowerCase();
		if (!term) return allCandidates;
		return allCandidates.filter((c) =>
			c.agent.name.toLowerCase().includes(term),
		);
	}, [allCandidates, search]);

	const handleSubagentAdded = (subagentId: string) => {
		onAdd(subagentId);
		// Close if no more eligible candidates (across the full set, not the
		// search-filtered view — otherwise a narrow search closes prematurely).
		const eligibleCount = allCandidates.filter((c) => !c.disabled).length;
		if (eligibleCount <= 1) {
			onOpenChange(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px] max-h-[600px]">
				<DialogHeader>
					<DialogTitle>Add subagent</DialogTitle>
				</DialogHeader>
				<div className="flex flex-col gap-4 overflow-y-auto">
					<SearchBar
						placeholder="Search agents..."
						value={search}
						onChange={setSearch}
					/>
					{candidates.length > 0 ? (
						<div className="max-h-[400px] flex flex-col gap-2 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							{candidates.map(({ agent: candidate, disabled, disabledReason }) => (
								<AgentCandidateCard
									key={candidate.id}
									candidate={candidate}
									onAdd={handleSubagentAdded}
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

"use client";

import { useState } from "react";
import { Plus, X, Info } from "lucide-react";
import { SubagentInfo } from "@/types/agents";
import { useAgentsStore } from "@/stores/agents-store";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import AddAgentSubagentDialog from "./add-agent-subagent-dialog";

interface AgentSubagentListProps {
	agentId: string;
	/** True when this agent is itself used as a subagent elsewhere. */
	isSubagent: boolean;
	subagentIds: string[];
	/** Display info for ids the store may not know (from agent.subagents). */
	fallbackSubagents?: SubagentInfo[];
	readOnly?: boolean;
	onChange?: (subagentIds: string[]) => void;
}

export default function AgentSubagentList({
	agentId,
	isSubagent,
	subagentIds,
	fallbackSubagents = [],
	readOnly,
	onChange,
}: AgentSubagentListProps) {
	const allAgents = useAgentsStore((state) => state.agents);
	const [dialogOpen, setDialogOpen] = useState(false);

	const resolve = (id: string): SubagentInfo => {
		const fromStore = allAgents.find((a) => a.id === id);
		if (fromStore) {
			return {
				id: fromStore.id,
				name: fromStore.name,
				emoji: fromStore.emoji,
				color: fromStore.color,
				description: fromStore.description,
			};
		}
		return (
			fallbackSubagents.find((s) => s.id === id) ?? {
				id,
				name: "Unknown agent",
			}
		);
	};

	const subagents = subagentIds.map(resolve);

	const handleRemove = (subagentId: string) => {
		onChange?.(subagentIds.filter((id) => id !== subagentId));
	};

	const handleAdd = (subagentId: string) => {
		onChange?.([...subagentIds, subagentId]);
	};

	// If this agent is used as a subagent elsewhere, show info banner instead
	if (isSubagent) {
		return (
			<div className="mt-7 flex flex-col">
				<span className="mb-3 font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
					SUBAGENTS
				</span>
				<div className="flex items-start gap-2.5 rounded-[10px] border border-border bg-card px-4 py-3.5">
					<Info className="mt-0.5 size-4 shrink-0 text-meta dark:text-panel-dim" />
					<p className="text-[12.5px] text-muted-foreground">
						This agent is already used as a subagent, it cannot have subagents.
					</p>
				</div>
			</div>
		);
	}

	return (
		<div className="mt-7 flex flex-col">
			<div className="mb-3 flex min-h-[24px] shrink-0 items-center justify-between">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
					SUBAGENTS{" "}
					<span className="tracking-normal text-meta dark:text-panel-dim">
						{subagents.length}
					</span>
				</span>
				{!readOnly && (
					<button
						className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80"
						onClick={() => { setDialogOpen(true); }}
					>
						<Plus className="size-3" />
						Add subagent
					</button>
				)}
			</div>
			{subagents.length > 0 ? (
				<div className="flex flex-col gap-2.5">
					{subagents.map((sub) => (
						<div
							key={sub.id}
							className="group flex items-center gap-3 rounded-[10px] border border-border bg-card px-4 py-3"
						>
							<AgentAvatar
								color={sub.color}
								emoji={sub.emoji}
								size="sm"
								shape="tile"
								className="text-base"
							/>
							<span className="min-w-0 flex-1">
								<span className="block truncate font-mono text-[12.5px] font-semibold text-petrol">
									{sub.name}
								</span>
								<span className="mt-0.5 block truncate text-xs text-muted-foreground">
									{sub.description || (
										<span className="text-faint dark:text-panel-dim">
											No description provided.
										</span>
									)}
								</span>
							</span>
							{!readOnly && (
								<button
									aria-label={`Remove ${sub.name}`}
									className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover hover:text-foreground dark:text-panel-dim dark:hover:bg-white/10"
									onClick={() => {
										handleRemove(sub.id);
									}}
								>
									<X className="size-3.5" />
								</button>
							)}
						</div>
					))}
				</div>
			) : (
				<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
					No subagents configured
				</div>
			)}

			{!readOnly && (
				<AddAgentSubagentDialog
					open={dialogOpen}
					onOpenChange={setDialogOpen}
					supervisorId={agentId}
					currentSubagentIds={subagentIds}
					onAdd={handleAdd}
				/>
			)}
		</div>
	);
}

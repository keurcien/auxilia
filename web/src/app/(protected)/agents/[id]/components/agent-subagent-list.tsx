"use client";

import { useState } from "react";
import { ChevronRight, Plus, X, Info, ArrowUpRight } from "lucide-react";
import { SubagentInfo } from "@/types/agents";
import { useAgentsStore } from "@/stores/agents-store";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import {
	AGENT_EDITOR_FORBIDDEN_MESSAGE,
	useOpenAgentEditor,
} from "@/hooks/use-open-agent-editor";
import { matchesQuery } from "@/lib/quick-search";
import AddAgentSubagentDialog from "./add-agent-subagent-dialog";
import { Switch } from "@/components/ui/switch";

interface AgentSubagentListProps {
	agentId: string;
	/** True when this agent is itself used as a subagent elsewhere. */
	isSubagent: boolean;
	subagentIds: string[];
	disabledByDefaultIds?: string[];
	/** Display info for ids the store may not know (from agent.subagents). */
	fallbackSubagents?: SubagentInfo[];
	readOnly?: boolean;
	canToggleDefault?: boolean;
	mode?: "agent" | "trigger";
	onChange?: (subagentIds: string[]) => void;
	onDefaultEnabledChange?: (subagentId: string, enabled: boolean) => void;
	/** Asked before a row navigates away to the subagent's page; return false
	 * to stay (the editor uses it to guard an unsaved draft). */
	confirmLeave?: () => boolean | Promise<boolean>;
	/** Quick search: only the subagents matching it are shown. */
	query?: string;
}

export default function AgentSubagentList({
	agentId,
	isSubagent,
	subagentIds,
	disabledByDefaultIds = [],
	fallbackSubagents = [],
	readOnly,
	canToggleDefault,
	mode = "agent",
	onChange,
	onDefaultEnabledChange,
	confirmLeave,
	query = "",
}: AgentSubagentListProps) {
	const allAgents = useAgentsStore((state) => state.agents);
	const [dialogOpen, setDialogOpen] = useState(false);
	const [expandedIds, setExpandedIds] = useState<Set<string>>(() => new Set());
	const { openAgentEditor, forbiddenOpen, setForbiddenOpen } =
		useOpenAgentEditor();

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

	const subagents = subagentIds
		.map(resolve)
		.sort((a, b) => a.name.localeCompare(b.name));
	const visibleSubagents = subagents.filter((sub) =>
		matchesQuery(query, sub.name, sub.description),
	);

	const handleRemove = (subagentId: string) => {
		onChange?.(subagentIds.filter((id) => id !== subagentId));
	};

	const handleAdd = (subagentId: string) => {
		onChange?.([...subagentIds, subagentId]);
	};

	// A row leads to the subagent's own page, gated on `editor` there; the
	// gate opens the "No access" dialog below when the viewer is too weak, and
	// only asks about leaving once access is confirmed.
	const handleOpen = (subagentId: string) => {
		void openAgentEditor(subagentId, { beforeNavigate: confirmLeave });
	};

	if (isSubagent) {
		return (
			<div className="mt-7 flex flex-col">
				<span className="mb-3 text-[10.5px] font-semibold text-label dark:text-muted-foreground">
					Subagents
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
				<span className="text-[10.5px] font-semibold text-label dark:text-muted-foreground">
					Subagents{" "}
					<span className="tracking-normal text-meta dark:text-panel-dim">
						{subagents.length}
					</span>
				</span>
				{!readOnly && (
					<button
						className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
						onClick={() => { setDialogOpen(true); }}
					>
						<Plus className="size-3" />
						Add subagent
					</button>
				)}
			</div>
			{visibleSubagents.length > 0 ? (
				<div className="flex flex-col gap-2.5">
					{visibleSubagents.map((sub) => {
						const isExpanded = expandedIds.has(sub.id);
						const enabledByDefault = !disabledByDefaultIds.includes(sub.id);
						return (
							<div
								key={sub.id}
								className={`overflow-hidden rounded-[10px] border border-border bg-card transition-opacity ${
									mode === "trigger" && !enabledByDefault
										? "opacity-50"
										: ""
								}`}
							>
							<button
								type="button"
								aria-expanded={isExpanded}
								aria-label={isExpanded ? "Collapse" : "Expand"}
								className="flex w-full cursor-pointer items-center gap-3 px-4 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40"
								onClick={() => {
									setExpandedIds((current) => {
										const next = new Set(current);
										if (isExpanded) next.delete(sub.id);
										else next.add(sub.id);
										return next;
									});
								}}
							>
								<AgentAvatar
									agentId={sub.id}
									name={sub.name}
									imageRevision={sub.imageRevision}
									color={sub.color}
									emoji={sub.emoji}
									size="sm"
									className="text-base"
								/>
								<span className="min-w-0 flex-1">
									<span className="block truncate text-[12.5px] font-semibold text-petrol">
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
								<ChevronRight
									aria-hidden="true"
									className={`size-4 shrink-0 text-meta transition-transform dark:text-panel-dim ${
										isExpanded ? "rotate-90" : ""
									}`}
								/>
							</button>
							{isExpanded && (
								<div className="border-t border-hover dark:border-white/5">
									<div className="flex items-center gap-3 bg-petrol-tint/55 px-4 py-3 dark:bg-white/5">
										<div className="min-w-0 flex-1">
											<p className="text-[12.5px] font-semibold text-foreground">
												{mode === "trigger"
													? "This trigger"
													: "New conversations"}
											</p>
											<p className="mt-0.5 text-[11.5px] text-muted-foreground">
												{mode === "trigger"
													? "Allow this subagent during automated runs"
													: "Enable this subagent by default"}
											</p>
										</div>
										<Switch
											checked={enabledByDefault}
											disabled={
												canToggleDefault === false ||
												(readOnly && !canToggleDefault)
											}
											onCheckedChange={(checked) => {
												onDefaultEnabledChange?.(sub.id, checked);
											}}
											aria-label={
												mode === "trigger"
													? `Allow ${sub.name} for this trigger`
													: `Enable ${sub.name} by default in new conversations`
											}
										/>
									</div>
									<div className="flex items-center justify-between border-t border-hover px-4 py-2 dark:border-white/5">
										<button
											type="button"
											className="flex cursor-pointer items-center gap-1 rounded-[7px] px-3 py-1.5 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
											onClick={() => {
												handleOpen(sub.id);
											}}
										>
											Open subagent
											<ArrowUpRight className="size-3.5" />
										</button>
										{!readOnly && (
											<button
												type="button"
												className="flex cursor-pointer items-center gap-1 rounded-[7px] px-3 py-1.5 text-[12.5px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] dark:hover:bg-[#B04A3A]/10"
												onClick={() => {
													handleRemove(sub.id);
												}}
											>
												<X className="size-3.5" />
												Disable {sub.name}
											</button>
										)}
									</div>
								</div>
							)}
							</div>
						);
					})}
				</div>
			) : (
				<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
					{subagents.length > 0
						? `No subagents match “${query.trim()}”`
						: "No subagents configured"}
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

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="No access"
				message={AGENT_EDITOR_FORBIDDEN_MESSAGE}
			/>
		</div>
	);
}

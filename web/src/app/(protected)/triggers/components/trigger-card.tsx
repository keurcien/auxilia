"use client";

import { useRouter } from "next/navigation";
import { Clock, MoreVertical, Pause, Pencil, Play, Trash2 } from "lucide-react";
import { Trigger } from "@/types/triggers";
import { describeSchedule, parseCronExpression } from "@/lib/triggers/schedule";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useAgentsStore } from "@/stores/agents-store";
import { useTriggersStore } from "@/stores/triggers-store";
import { useRunTrigger } from "@/hooks/use-run-trigger";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";

interface TriggerCardProps {
	trigger: Trigger;
	onDelete: (id: string) => void;
}

export default function TriggerCard({ trigger, onDelete }: TriggerCardProps) {
	const router = useRouter();
	const updateTrigger = useTriggersStore((state) => state.updateTrigger);
	const runTrigger = useRunTrigger();
	const agent = useAgentsStore((state) =>
		state.agents.find((a) => a.id === trigger.agentId),
	);

	const frequency = describeSchedule(parseCronExpression(trigger.cronExpression));

	const handleRunNow = () => {
		runTrigger(trigger).catch((error: unknown) => {
			console.error("Error running trigger:", error);
			alert(getApiErrorMessage(error, "Failed to run the trigger. Please try again."));
		});
	};

	const handleToggleActive = () => {
		updateTrigger(trigger.id, { isActive: !trigger.isActive }).catch(
			(error: unknown) => {
				console.error("Error updating trigger:", error);
				alert("Failed to update trigger. Please try again.");
			},
		);
	};

	return (
		<div
			className="group flex h-full flex-col gap-3 rounded-2xl border border-[#E9EEEB] dark:border-white/10 bg-white dark:bg-card p-5 cursor-pointer transition-[border-color,box-shadow] duration-[130ms] ease-out hover:border-[#D7E0DB] dark:hover:border-white/20 hover:shadow-[0_6px_18px_-4px_rgba(33,36,31,0.08)]"
			onClick={() => {
				router.push(`/triggers/${trigger.id}`);
			}}
		>
			{/* Head: status dot · name · menu (on hover) */}
			<div className="flex min-h-[30px] min-w-0 items-center gap-2.5">
				<span
					className={`size-2 shrink-0 rounded-full ${
						trigger.isActive ? "bg-[#3D8B63]" : "bg-[#C2CFC8]"
					}`}
				/>
				<div className="min-w-0 flex-1 truncate font-[family-name:var(--font-jakarta-sans)] text-[17px] font-bold tracking-[-0.012em] text-[#1A2620] dark:text-foreground">
					{trigger.name}
				</div>
				<div
					onClick={(e) => {
						e.stopPropagation();
					}}
				>
					<SageDropdownMenu
						trigger={
							<button
								type="button"
								className="flex size-[30px] items-center justify-center rounded-lg cursor-pointer opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100 hover:bg-[#F4F8F5] dark:hover:bg-white/5"
							>
								<MoreVertical className="size-[18px] text-[#9AA8A1]" />
								<span className="sr-only">Trigger options</span>
							</button>
						}
						items={[
							{
								label: "Run now",
								icon: <Play />,
								onClick: handleRunNow,
							},
							{
								label: trigger.isActive ? "Pause" : "Resume",
								icon: trigger.isActive ? <Pause /> : <Play />,
								onClick: handleToggleActive,
							},
							{
								label: "Edit",
								icon: <Pencil />,
								onClick: () => {
									router.push(`/triggers/${trigger.id}`);
								},
							},
							{ separator: true as const },
							{
								label: "Delete",
								icon: <Trash2 />,
								destructive: true,
								onClick: () => {
									onDelete(trigger.id);
								},
							},
						]}
					/>
				</div>
			</div>

			{/* Instructions excerpt */}
			<p className="flex-1 font-[family-name:var(--font-dm-sans)] text-[13.5px] leading-[1.45] text-[#6B7F76] dark:text-muted-foreground line-clamp-1">
				{trigger.instructions}
			</p>

			{/* Chips: agent · frequency */}
			<div className="flex flex-wrap gap-2 border-t border-[#F0F3F1] dark:border-white/5 pt-3.5">
				<div className="flex h-[30px] items-center gap-1.75 rounded-full border border-[#ECF1EE] dark:border-white/10 bg-[#F4F7F5] dark:bg-white/5 pl-1.5 pr-3">
					<AgentAvatar
						color={agent?.color}
						emoji={agent?.emoji}
						size="xs"
						className="size-5! text-[11px]!"
					/>
					<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px] font-semibold text-[#4A5B53] dark:text-white/80">
						{agent?.name ?? "Unknown agent"}
					</span>
				</div>
				<div className="flex h-[30px] items-center gap-1.5 rounded-full border border-[#ECF1EE] dark:border-white/10 bg-[#F4F7F5] dark:bg-white/5 px-3">
					<Clock className="size-[13px] shrink-0 text-[#7C8C84] dark:text-muted-foreground" />
					<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px] font-medium text-[#4A5B53] dark:text-white/80">
						{frequency}
					</span>
				</div>
			</div>
		</div>
	);
}

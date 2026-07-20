"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlarmClock, Play, Trash2, TriangleAlert } from "lucide-react";
import { Trigger } from "@/types/triggers";
import {
	describeSchedule,
	formatRunAt,
	parseCronExpression,
} from "@/lib/triggers/schedule";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useTriggersStore } from "@/stores/triggers-store";
import { useAgentsStore } from "@/stores/agents-store";
import { useRunTrigger } from "@/hooks/use-run-trigger";
import { EditorHeader } from "@/components/editor/editor-header";
import { EditorSection } from "@/components/editor/editor-section";
import { AgentPicker } from "@/components/editor/agent-picker";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";
import { SageButton } from "@/components/ui/sage-button";
import { Switch } from "@/components/ui/switch";
import TriggerEditor from "@/app/(protected)/triggers/components/trigger-editor";
import TriggerSummaryBanner from "@/app/(protected)/triggers/components/trigger-summary-banner";
import RunHistoryCard from "@/app/(protected)/triggers/components/run-history-card";

interface TriggerDetailProps {
	trigger: Trigger;
}

export default function TriggerDetail({ trigger }: TriggerDetailProps) {
	const router = useRouter();
	const upsertTrigger = useTriggersStore((state) => state.upsertTrigger);
	const updateTrigger = useTriggersStore((state) => state.updateTrigger);
	const deleteTrigger = useTriggersStore((state) => state.deleteTrigger);
	const runTrigger = useRunTrigger();
	const liveTrigger = useTriggersStore(
		(state) => state.triggers.find((t) => t.id === trigger.id) ?? trigger,
	);
	const agent = useAgentsStore((state) =>
		state.agents.find((a) => a.id === liveTrigger.agentId),
	);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);

	const [mode, setMode] = useState<"read" | "edit">("read");
	const [isRunning, setIsRunning] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		upsertTrigger(trigger);
	}, [trigger, upsertTrigger]);

	useEffect(() => {
		fetchAgents().catch(() => {});
	}, [fetchAgents]);

	const handleToggleActive = (isActive: boolean) => {
		setError(null);
		updateTrigger(liveTrigger.id, { isActive }).catch((err: unknown) => {
			setError(getApiErrorMessage(err, "Failed to update the trigger."));
		});
	};

	const handleRunNow = async () => {
		setIsRunning(true);
		setError(null);
		try {
			// No navigation — the run shows up in the sidebar with a loading dot.
			await runTrigger(liveTrigger);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to run the trigger."));
		} finally {
			setIsRunning(false);
		}
	};

	const handleDelete = async () => {
		if (!confirm("Are you sure you want to delete this trigger?")) {
			return;
		}
		setError(null);
		try {
			await deleteTrigger(liveTrigger.id);
			router.push("/triggers");
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to delete the trigger."));
		}
	};

	const schedule = parseCronExpression(liveTrigger.cronExpression);

	if (mode === "edit") {
		return (
			<div className="px-8 py-6">
				<TriggerEditor
					trigger={liveTrigger}
					onSaved={() => {
						setMode("read");
					}}
					onCancel={() => {
						setMode("read");
					}}
				/>
			</div>
		);
	}

	return (
		<div className="px-8 py-6">
			<div className="flex flex-col font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
				<EditorHeader
					icon={<AlarmClock className="size-[23px]" />}
					iconClassName="bg-[#E6F2EB] dark:bg-emerald-950/40 text-[#2F7F57] dark:text-emerald-400"
					title={liveTrigger.name}
					subtitle={
						<>
							<Switch
								checked={liveTrigger.isActive}
								onCheckedChange={handleToggleActive}
								className="data-[state=checked]:bg-[#3D8B63] cursor-pointer"
							/>
							<span
								className={`text-[13px] font-semibold ${
									liveTrigger.isActive
										? "text-[#3D8B63] dark:text-emerald-400"
										: "text-[#7D8C84] dark:text-white/60"
								}`}
							>
								{liveTrigger.isActive ? "Active" : "Paused"}
							</span>
							<span className="size-[3px] rounded-full bg-[#C4D0CA] dark:bg-white/20" />
							<span className="text-[12.5px] font-medium text-[#94A59D] dark:text-muted-foreground">
								{liveTrigger.isActive
									? liveTrigger.nextRunAt
										? `Next run ${formatRunAt(liveTrigger.nextRunAt, liveTrigger.timezone)}`
										: "Next run pending"
									: "No scheduled runs"}
							</span>
						</>
					}
					actions={
						<>
							<SageButton
								color="destructive-ghost"
								className="size-10 p-0! border-[1.5px] border-[#F0DAD3] dark:border-[#D45B45]/30 bg-white dark:bg-transparent"
								title="Delete trigger"
								onClick={() => {
									void handleDelete();
								}}
							>
								<Trash2 className="size-4" />
							</SageButton>
							<SageButton
								color="outline"
								className="size-10 p-0!"
								disabled={isRunning}
								title="Run now"
								onClick={() => {
									void handleRunNow();
								}}
							>
								<Play className="size-[14px] text-[#3D8B63]" />
							</SageButton>
							<SageButton
								color="dark"
								onClick={() => {
									setMode("edit");
								}}
							>
								Edit
							</SageButton>
						</>
					}
				/>

				{!liveTrigger.modelAvailable && (
					<div className="mt-5 flex items-start gap-2.5 rounded-[14px] bg-[#FDF6EC] dark:bg-amber-950/30 px-4 py-3 text-[13.5px] font-medium text-[#B4643C] dark:text-amber-400">
						<TriangleAlert className="size-4 shrink-0 mt-0.5" />
						<span>
							The model used by this trigger (
							{liveTrigger.modelDisplayName ?? liveTrigger.modelId}) is no
							longer available in this workspace, so scheduled runs are being
							skipped. Choose another model in Edit, or ask a workspace admin to
							re-enable it.
						</span>
					</div>
				)}

				{error && (
					<div className="mt-5 rounded-[14px] bg-[#FFF5F3] dark:bg-[#D45B45]/10 px-4 py-3 text-[13.5px] font-medium text-[#D45B45]">
						{error}
					</div>
				)}

				<div className="flex flex-col md:flex-row gap-8 mt-7">
					{/* Left: summary + agent + instructions (read-only) */}
					<div className="flex flex-col gap-7 flex-1 min-w-0 pt-2">
						<TriggerSummaryBanner
							trigger={liveTrigger}
							agentName={agent?.name ?? "the agent"}
						/>

						<EditorSection label="Agent">
							<AgentPicker
								value={liveTrigger.agentId}
								onChange={() => {}}
								disabled
							/>
						</EditorSection>

						<EditorSection label="Instructions">
							<div className="flex flex-col rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card p-[18px] shadow-[0_1px_3px_rgba(33,36,31,0.04)]">
								<p className="whitespace-pre-wrap text-[14.5px] font-medium text-[#3A4A43] dark:text-white leading-[1.6]">
									{liveTrigger.instructions}
								</p>
								<div className="flex items-center justify-between shrink-0 mt-4 pt-3.5 border-t border-[#edf2ef] dark:border-white/5">
									<ModelPickerChip
										value={liveTrigger.modelId}
										onChange={() => {}}
										disabled
										unavailableLabel={liveTrigger.modelDisplayName}
									/>
								</div>
							</div>
						</EditorSection>

						<EditorSection label="Frequency">
							<div className="flex items-center rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card px-4.5 py-5 shadow-[0_1px_3px_rgba(33,36,31,0.04)]">
								<span className="text-[15px] font-semibold text-[#1E2D28] dark:text-white">
									{describeSchedule(schedule).replace(" · ", " at ")}
								</span>
							</div>
						</EditorSection>
					</div>

					{/* Right: run history */}
					<div className="flex flex-col gap-7 w-full md:w-1/2">
						<EditorSection label="Run history" hint="Last 30 days">
							<RunHistoryCard
								triggerId={liveTrigger.id}
								timezone={liveTrigger.timezone}
							/>
						</EditorSection>
					</div>
				</div>
			</div>
		</div>
	);
}

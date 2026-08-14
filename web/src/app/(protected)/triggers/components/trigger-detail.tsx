"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { AlarmClock, Play, TriangleAlert } from "lucide-react";
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
import {
	HeaderButton,
	HeaderPrimaryButton,
	SubpageHeader,
} from "@/components/layout/subpage-header";
import { EditorHeader } from "@/components/editor/editor-header";
import { EditorSection } from "@/components/editor/editor-section";
import { AgentPicker } from "@/components/editor/agent-picker";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { Switch } from "@/components/ui/switch";
import TriggerEditor from "@/app/(protected)/triggers/components/trigger-editor";
import TriggerSummaryBanner from "@/app/(protected)/triggers/components/trigger-summary-banner";
import RunHistoryCard from "@/app/(protected)/triggers/components/run-history-card";

const slugify = (name: string) =>
	name.trim().toLowerCase().replace(/\s+/g, "-") || "…";

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
			<TriggerEditor
				trigger={liveTrigger}
				onSaved={() => {
					setMode("read");
				}}
				onCancel={() => {
					setMode("read");
				}}
			/>
		);
	}

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={[
					{ label: "workspace" },
					{ label: "triggers", href: "/triggers" },
					{ label: slugify(liveTrigger.name) },
				]}
			>
				<HeaderButton
					accent
					disabled={isRunning}
					onClick={() => {
						void handleRunNow();
					}}
				>
					<Play className="size-3" fill="currentColor" />
					{isRunning ? "Starting…" : "Run now"}
				</HeaderButton>
				<HeaderPrimaryButton
					onClick={() => {
						setMode("edit");
					}}
				>
					Edit
				</HeaderPrimaryButton>
				<SageDropdownMenu
					items={[
						{
							label: "Delete trigger",
							destructive: true,
							onClick: () => {
								void handleDelete();
							},
						},
					]}
				/>
			</SubpageHeader>

			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-7 sm:px-7 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				<div className="w-full">
					<EditorHeader
						icon={<AlarmClock className="size-[22px]" />}
						iconClassName="bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal"
						title={liveTrigger.name}
						subtitle={
							<>
								<Switch
									checked={liveTrigger.isActive}
									onCheckedChange={handleToggleActive}
									className="cursor-pointer data-[state=checked]:bg-success"
								/>
								<span
									className={`text-[13px] font-semibold ${
										liveTrigger.isActive
											? "text-success dark:text-emerald-400"
											: "text-meta dark:text-panel-dim"
									}`}
								>
									{liveTrigger.isActive ? "Active" : "Paused"}
								</span>
								<span className="size-[3px] rounded-full bg-faint dark:bg-white/20" />
								<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
									{liveTrigger.isActive
										? liveTrigger.nextRunAt
											? `Next run ${formatRunAt(liveTrigger.nextRunAt, liveTrigger.timezone)}`
											: "Next run pending"
										: "No scheduled runs"}
								</span>
							</>
						}
					/>

					{!liveTrigger.modelAvailable && (
						<div className="mt-5 flex items-start gap-2.5 rounded-[10px] bg-warning-bg px-4 py-3 text-[13.5px] font-medium text-warning dark:bg-amber-950/30 dark:text-amber-400">
							<TriangleAlert className="mt-0.5 size-4 shrink-0" />
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
						<div className="mt-5 rounded-[10px] bg-destructive/10 px-4 py-3 text-[13.5px] font-medium text-destructive">
							{error}
						</div>
					)}

					<div className="mt-7 flex flex-col gap-8 md:flex-row">
						{/* Left: summary + agent + instructions (read-only) */}
						<div className="flex min-w-0 flex-1 flex-col gap-7 pt-2">
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
								<div className="flex flex-col rounded-[10px] border border-border bg-sidebar p-4 dark:bg-white/5">
									<p className="whitespace-pre-wrap font-mono text-[12.5px] leading-[1.7] text-foreground">
										{liveTrigger.instructions}
									</p>
									<div className="mt-4 flex shrink-0 items-center justify-between border-t border-hairline pt-3.5 dark:border-white/5">
										<ModelPickerChip
											value={liveTrigger.modelId}
											onChange={() => {}}
											disabled
											unavailable={!liveTrigger.modelAvailable}
											unavailableLabel={liveTrigger.modelDisplayName}
										/>
									</div>
								</div>
							</EditorSection>

							<EditorSection label="Frequency">
								<div className="flex items-center rounded-[10px] border border-border bg-card px-4.5 py-[18px]">
									<span className="text-[15px] font-semibold text-foreground">
										{describeSchedule(schedule).replace(" · ", " at ")}
									</span>
								</div>
							</EditorSection>
						</div>

						{/* Right: run history */}
						<div className="flex w-full flex-col gap-7 md:w-1/2">
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
		</div>
	);
}

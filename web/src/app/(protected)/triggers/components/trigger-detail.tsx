"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
	AlarmClock,
	Check,
	Copy,
	Play,
	TriangleAlert,
	Webhook,
} from "lucide-react";
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
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import {
	HeaderButton,
	HeaderPrimaryButton,
	SubpageHeader,
} from "@/components/layout/subpage-header";
import { EditorHeader } from "@/components/editor/editor-header";
import { EditorSection } from "@/components/editor/editor-section";
import { AgentPicker } from "@/components/editor/agent-picker";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
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
	const confirmDialog = useConfirmDialog();
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
	const [copied, setCopied] = useState(false);
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
		if (
			!(await confirmDialog({
				title: "Delete this trigger?",
				description:
					"Its configuration will be removed permanently. Existing run history is unaffected.",
				confirmLabel: "Delete trigger",
				destructive: true,
			}))
		) {
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

	const schedule =
		liveTrigger.triggerType === "schedule"
			? parseCronExpression(liveTrigger.cronExpression)
			: null;

	const handleCopyWebhook = async () => {
		if (liveTrigger.triggerType !== "webhook") return;
		try {
			await navigator.clipboard.writeText(liveTrigger.webhookUrl);
			setCopied(true);
			window.setTimeout(() => {
				setCopied(false);
			}, 1800);
		} catch {
			setError("Could not copy the webhook URL.");
		}
	};

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
				<DropdownMenu
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
						icon={
							liveTrigger.triggerType === "schedule" ? (
								<AlarmClock className="size-[22px]" />
							) : (
								<Webhook className="size-[22px]" />
							)
						}
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
								<span className="text-[11px] text-meta dark:text-panel-dim">
									{liveTrigger.triggerType === "webhook" ? (
										liveTrigger.isActive ? (
											"Listening for POST requests"
										) : (
											"Webhook disabled"
										)
									) : liveTrigger.isActive && liveTrigger.nextRunAt ? (
										<>
											Next run{" "}
											<span className="font-mono">
												{formatRunAt(
													liveTrigger.nextRunAt,
													liveTrigger.timezone,
												)}
											</span>
										</>
									) : liveTrigger.isActive ? (
										"Next run pending"
									) : (
										"No scheduled runs"
									)}
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
								longer available in this workspace, so this trigger cannot run.
								Choose another model in Edit, or ask a workspace admin to
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
									<p className="whitespace-pre-wrap text-[12.5px] leading-[1.7] text-foreground">
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

							{liveTrigger.triggerType === "schedule" && schedule ? (
								<EditorSection label="Frequency">
									<div className="flex items-center rounded-[10px] border border-border bg-card px-4.5 py-[18px]">
										<span className="text-[15px] font-semibold text-foreground">
											{describeSchedule(schedule).replace(
												/, (?=[^,]*$)/,
												" at ",
											)}
										</span>
									</div>
								</EditorSection>
							) : liveTrigger.triggerType === "webhook" ? (
								<EditorSection
									label="Webhook endpoint"
									hint="Keep this URL private"
								>
									<div className="overflow-hidden rounded-[10px] border border-border bg-card">
										<div className="flex items-center gap-3 p-3">
											<code className="min-w-0 flex-1 truncate rounded-md bg-sidebar px-3 py-2.5 text-[11.5px] text-foreground dark:bg-white/5">
												{liveTrigger.webhookUrl}
											</code>
											<button
												type="button"
												onClick={() => {
													void handleCopyWebhook();
												}}
												className="flex h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-lg bg-petrol px-3 text-[11.5px] font-semibold text-white transition-opacity hover:opacity-90"
											>
												{copied ? (
													<Check className="size-3.5" />
												) : (
													<Copy className="size-3.5" />
												)}
												{copied ? "Copied" : "Copy"}
											</button>
										</div>
										<div className="border-t border-hairline px-4 py-3 dark:border-white/5">
											<p className="text-[11.5px] leading-5 text-meta dark:text-panel-dim">
												Send JSON with optional{" "}
												<code>agent_id</code>, <code>model_id</code>, and{" "}
												<code>instructions</code>. Omitted fields use the
												defaults above.
											</p>
										</div>
									</div>
								</EditorSection>
							) : null}
						</div>

						{/* Right: run history */}
						<div className="flex w-full flex-col gap-7 md:w-1/2">
							<EditorSection label="Run history" hint="Last 30 days">
								<RunHistoryCard
									triggerId={liveTrigger.id}
									timezone={
										liveTrigger.triggerType === "schedule"
											? liveTrigger.timezone
											: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"
									}
								/>
							</EditorSection>
						</div>
					</div>
				</div>
			</div>
		</div>
	);
}

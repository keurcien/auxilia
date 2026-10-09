"use client";

import { useEffect, useMemo, useState } from "react";
import { Braces, Webhook } from "lucide-react";
import { Trigger, TriggerType } from "@/types/triggers";
import {
	buildCronExpression,
	DEFAULT_SCHEDULE,
	parseCronExpression,
	Schedule,
} from "@/lib/triggers/schedule";
import { getApiErrorMessage } from "@/lib/api/errors";
import { getDefaultModel } from "@/lib/utils/get-default-model";
import { useTriggersStore } from "@/stores/triggers-store";
import { useModelsStore } from "@/stores/models-store";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import {
	SubpageHeader,
	UnsavedBadge,
} from "@/components/layout/subpage-header";
import { EditorSection } from "@/components/editor/editor-section";
import { SaveActions } from "@/components/editor/save-actions";
import { AgentPicker } from "@/components/editor/agent-picker";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";
import { GroupPicker } from "@/components/ui/group-picker";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import type { ResourceVisibility } from "@/types/visibility";
import { groupOptions } from "@/lib/groups";
import ScheduleBuilder from "@/app/(protected)/triggers/components/schedule-builder";
import NextRunsCard from "@/app/(protected)/triggers/components/next-runs-card";

const slugify = (name: string) =>
	name.trim().toLowerCase().replace(/\s+/g, "-") || "…";

interface TriggerFormState {
	name: string;
	group: string;
	instructions: string;
	agentId: string | null;
	modelId: string | null;
	schedule: Schedule;
	timezone: string;
	visibility: ResourceVisibility;
	teamIds: string[];
}

function browserTimezone(): string {
	return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function defaultForm(): TriggerFormState {
	return {
		name: "",
		group: "",
		instructions: "",
		agentId: null,
		modelId: null,
		schedule: DEFAULT_SCHEDULE,
		timezone: browserTimezone(),
		visibility: "personal",
		teamIds: [],
	};
}

function fromTrigger(trigger: Trigger): TriggerFormState {
	return {
		name: trigger.name,
		group: trigger.group ?? "",
		instructions: trigger.instructions,
		agentId: trigger.agentId,
		modelId: trigger.modelId,
		schedule:
			trigger.triggerType === "schedule"
				? parseCronExpression(trigger.cronExpression)
				: DEFAULT_SCHEDULE,
		timezone:
			trigger.triggerType === "schedule"
				? trigger.timezone
				: browserTimezone(),
		visibility: trigger.visibility,
		teamIds: trigger.teamIds,
	};
}

function toComparablePayload(form: TriggerFormState, triggerType: TriggerType) {
	return {
		name: form.name.trim(),
		group: form.group || null,
		instructions: form.instructions.trim(),
		agentId: form.agentId,
		modelId: form.modelId,
		visibility: form.visibility,
		teamIds: [...form.teamIds].sort(),
		...(triggerType === "schedule"
			? {
					cronExpression: buildCronExpression(form.schedule),
					timezone: form.timezone,
				}
			: {}),
	};
}

interface TriggerEditorProps {
	/** Undefined = create mode. */
	trigger?: Trigger;
	triggerType?: TriggerType;
	onSaved: (trigger: Trigger) => void;
	onCancel?: () => void;
}

export default function TriggerEditor({
	trigger,
	triggerType,
	onSaved,
	onCancel,
}: TriggerEditorProps) {
	const createTrigger = useTriggersStore((state) => state.createTrigger);
	const updateTrigger = useTriggersStore((state) => state.updateTrigger);
	const triggers = useTriggersStore((state) => state.triggers);
	const fetchTriggers = useTriggersStore((state) => state.fetchTriggers);
	const models = useModelsStore((state) => state.models);
	const confirmDialog = useConfirmDialog();
	const type = trigger?.triggerType ?? triggerType ?? "schedule";

	const initialForm = useMemo(
		() => (trigger ? fromTrigger(trigger) : defaultForm()),
		[trigger],
	);
	const [form, setForm] = useState<TriggerFormState>(initialForm);
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const availableGroups = useMemo(() => groupOptions(triggers), [triggers]);

	useEffect(() => {
		fetchTriggers().catch(() => {});
	}, [fetchTriggers]);

	const setField = <K extends keyof TriggerFormState>(
		key: K,
		value: TriggerFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const selectedModelId =
		form.modelId ?? (trigger ? null : (getDefaultModel(models) ?? null));

	const cronExpression = buildCronExpression(form.schedule);
	const isDirty =
		JSON.stringify(toComparablePayload(form, type)) !==
		JSON.stringify(toComparablePayload(initialForm, type));
	const canSave = Boolean(
		form.name.trim() &&
		form.instructions.trim() &&
		form.agentId &&
		selectedModelId &&
		(type === "webhook" || cronExpression) &&
		(form.visibility !== "teams" || form.teamIds.length > 0),
	);

	const handleSave = async () => {
		if (!canSave || !form.agentId || !selectedModelId) return;
		if (type === "schedule" && !cronExpression) return;
		setIsSaving(true);
		setError(null);
		const commonPayload = {
			name: form.name.trim(),
			group: form.group || null,
			instructions: form.instructions.trim(),
			agentId: form.agentId,
			modelId: selectedModelId,
			visibility: form.visibility,
			teamIds: form.teamIds,
		};
		try {
			let saved: Trigger;
			if (type === "schedule") {
				if (!cronExpression) return;
				const schedulePayload = {
					...commonPayload,
					cronExpression,
					timezone: form.timezone,
				};
				saved = trigger
					? await updateTrigger(trigger.id, schedulePayload)
					: await createTrigger({
							...schedulePayload,
							triggerType: "schedule",
							isActive: true,
						});
			} else {
				saved = trigger
					? await updateTrigger(trigger.id, commonPayload)
					: await createTrigger({
							...commonPayload,
							triggerType: "webhook",
							isActive: true,
						});
			}
			onSaved(saved);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save the trigger."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleCancel = async () => {
		if (
			isDirty &&
			!(await confirmDialog({
				title: "Discard unsaved changes?",
				description: "Your trigger edits will be lost and cannot be recovered.",
				confirmLabel: "Discard changes",
				destructive: true,
			}))
		) {
			return;
		}
		onCancel?.();
	};

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={[
					{ label: "workspace" },
					{ label: "triggers", href: "/triggers" },
					{ label: trigger ? slugify(trigger.name) : "new" },
				]}
				badge={isDirty ? <UnsavedBadge /> : undefined}
			>
				<SaveActions
					isDirty={isDirty}
					isSaving={isSaving}
					canSave={canSave}
					onSave={() => {
						void handleSave();
					}}
					onCancel={
						onCancel
							? () => {
									void handleCancel();
								}
							: undefined
					}
					saveLabel={trigger ? "Save changes" : "Create trigger"}
				/>
			</SubpageHeader>

			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-7 sm:px-7 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				<div className="w-full">
					{error && (
						<div className="mb-5 rounded-[10px] bg-destructive/10 px-4 py-3 text-[13.5px] font-medium text-destructive">
							{error}
						</div>
					)}

					<div className="flex flex-col gap-8 md:flex-row">
						{/* Left: name, agent, instructions */}
						<div className="flex min-w-0 flex-1 flex-col gap-7">
							<EditorSection label="Trigger name">
								<input
									type="text"
									maxLength={255}
									value={form.name}
									onChange={(e) => {
										setField("name", e.target.value);
									}}
									placeholder="What does this trigger do?"
									className="w-full rounded-[10px] border border-input bg-card px-3.5 py-3 text-[15px] font-semibold leading-[1.5] text-foreground outline-none transition-[border-color,box-shadow] placeholder:font-medium placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
								/>
							</EditorSection>

							<GroupPicker
								value={form.group}
								groups={availableGroups}
								onChange={(group) => {
									setField("group", group);
								}}
							/>
							<VisibilityPicker
								visibility={form.visibility}
								teamIds={form.teamIds}
								onChange={(visibility, teamIds) => {
									setForm((current) => ({
										...current,
										visibility,
										teamIds,
									}));
								}}
							/>

							<EditorSection label="Agent">
								<AgentPicker
									value={form.agentId}
									onChange={(agentId) => {
										setField("agentId", agentId);
									}}
								/>
							</EditorSection>

							<EditorSection label="Instructions" className="flex-1">
								<div className="flex min-h-[300px] flex-1 flex-col rounded-[10px] border border-input bg-sidebar p-4 transition-[border-color,box-shadow] focus-within:border-petrol focus-within:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] dark:bg-white/5">
									<textarea
										value={form.instructions}
										onChange={(e) => {
											setField("instructions", e.target.value);
										}}
										placeholder="The message sent to the agent on every run…"
										className="w-full flex-1 resize-none border-none bg-transparent text-[12.5px] leading-[1.7] text-foreground placeholder:text-meta dark:placeholder:text-panel-dim focus:outline-none [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
									/>
									<div className="mt-4 flex shrink-0 items-center border-t border-hairline pt-3.5 dark:border-white/5">
										<ModelPickerChip
											value={selectedModelId}
											onChange={(modelId) => {
												setField("modelId", modelId);
											}}
											unavailable={
												trigger && selectedModelId === trigger.modelId
													? !trigger.modelAvailable
													: undefined
											}
											unavailableLabel={
												trigger && selectedModelId === trigger.modelId
													? trigger.modelDisplayName
													: undefined
											}
										/>
									</div>
								</div>
							</EditorSection>
						</div>

						{/* Right: type-specific configuration */}
						<div className="flex w-full flex-col gap-7 md:w-1/2">
							{type === "schedule" ? (
								<EditorSection label="Frequency">
									<div className="flex flex-col rounded-[10px] border border-border bg-card">
										<div className="p-5">
											<ScheduleBuilder
												bare
												value={form.schedule}
												onChange={(schedule) => {
													setField("schedule", schedule);
												}}
												timezone={form.timezone}
												onTimezoneChange={(timezone) => {
													setField("timezone", timezone);
												}}
											/>
										</div>
										<div className="border-t border-hairline px-4.5 pt-2.5 pb-1.5 dark:border-white/5">
											<div className="px-0.5 pb-1 text-[10.5px] font-semibold text-meta dark:text-panel-dim">
												Next runs
											</div>
											<NextRunsCard
												bare
												cronExpression={cronExpression}
												timezone={form.timezone}
											/>
										</div>
									</div>
								</EditorSection>
							) : (
								<EditorSection label="Webhook">
									<div className="overflow-hidden rounded-[10px] border border-border bg-card">
										<div className="flex gap-3.5 p-5">
											<div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal">
												<Webhook className="size-5" />
											</div>
											<div>
												<p className="text-[14px] font-semibold text-foreground">
													A unique URL will be generated
												</p>
												<p className="mt-1 text-[12.5px] leading-5 text-meta dark:text-panel-dim">
													Each POST starts a fresh thread. You can copy the
													endpoint after creating the trigger.
												</p>
											</div>
										</div>
										<div className="border-t border-hairline bg-sidebar/60 p-5 dark:border-white/5 dark:bg-white/3">
											<div className="mb-3 flex items-center gap-2">
												<Braces className="size-3.5 text-petrol dark:text-panel-terminal" />
												<span className="text-[11px] font-semibold text-foreground">
													Optional POST overrides
												</span>
											</div>
											<pre className="overflow-x-auto rounded-lg bg-foreground px-4 py-3 text-[11.5px] leading-5 text-background">
{`{
  "agent_id": "uuid",
  "model_id": "provider/model",
  "instructions": "Run-specific prompt"
}`}
											</pre>
											<p className="mt-3 text-[11.5px] leading-5 text-meta dark:text-panel-dim">
												Any omitted value falls back to this trigger&apos;s
												configuration.
											</p>
										</div>
									</div>
								</EditorSection>
							)}
						</div>
					</div>
				</div>
			</div>
		</div>
	);
}

"use client";

import { useEffect, useMemo, useState } from "react";
import { Trigger } from "@/types/triggers";
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
import {
	SubpageHeader,
	UnsavedBadge,
} from "@/components/layout/subpage-header";
import { EditorSection } from "@/components/editor/editor-section";
import { SaveActions } from "@/components/editor/save-actions";
import { AgentPicker } from "@/components/editor/agent-picker";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";
import ScheduleBuilder from "@/app/(protected)/triggers/components/schedule-builder";
import NextRunsCard from "@/app/(protected)/triggers/components/next-runs-card";

const slugify = (name: string) =>
	name.trim().toLowerCase().replace(/\s+/g, "-") || "…";

interface TriggerFormState {
	name: string;
	instructions: string;
	agentId: string | null;
	modelId: string | null;
	schedule: Schedule;
	timezone: string;
}

function browserTimezone(): string {
	return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

function defaultForm(): TriggerFormState {
	return {
		name: "",
		instructions: "",
		agentId: null,
		modelId: null,
		schedule: DEFAULT_SCHEDULE,
		timezone: browserTimezone(),
	};
}

function fromTrigger(trigger: Trigger): TriggerFormState {
	return {
		name: trigger.name,
		instructions: trigger.instructions,
		agentId: trigger.agentId,
		modelId: trigger.modelId,
		schedule: parseCronExpression(trigger.cronExpression),
		timezone: trigger.timezone,
	};
}

function toPayload(form: TriggerFormState) {
	return {
		name: form.name.trim(),
		instructions: form.instructions.trim(),
		agentId: form.agentId,
		modelId: form.modelId,
		cronExpression: buildCronExpression(form.schedule),
		timezone: form.timezone,
	};
}

interface TriggerEditorProps {
	/** Undefined = create mode. */
	trigger?: Trigger;
	onSaved: (trigger: Trigger) => void;
	onCancel?: () => void;
}

export default function TriggerEditor({
	trigger,
	onSaved,
	onCancel,
}: TriggerEditorProps) {
	const createTrigger = useTriggersStore((state) => state.createTrigger);
	const updateTrigger = useTriggersStore((state) => state.updateTrigger);
	const models = useModelsStore((state) => state.models);

	const initialForm = useMemo(
		() => (trigger ? fromTrigger(trigger) : defaultForm()),
		[trigger],
	);
	const [form, setForm] = useState<TriggerFormState>(initialForm);
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const setField = <K extends keyof TriggerFormState>(
		key: K,
		value: TriggerFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	// Create mode: preselect the default model once the catalog loads.
	useEffect(() => {
		if (trigger || form.modelId !== null || models.length === 0) return;
		const defaultModel = getDefaultModel(models);
		if (defaultModel) {
			setField("modelId", defaultModel);
		}
	}, [trigger, form.modelId, models]);

	const cronExpression = buildCronExpression(form.schedule);
	const isDirty =
		JSON.stringify(toPayload(form)) !== JSON.stringify(toPayload(initialForm));
	const canSave = Boolean(
		form.name.trim() &&
		form.instructions.trim() &&
		form.agentId &&
		form.modelId &&
		cronExpression,
	);

	const handleSave = async () => {
		if (!canSave || !form.agentId || !form.modelId || !cronExpression) return;
		setIsSaving(true);
		setError(null);
		const payload = {
			name: form.name.trim(),
			instructions: form.instructions.trim(),
			agentId: form.agentId,
			modelId: form.modelId,
			cronExpression,
			timezone: form.timezone,
		};
		try {
			const saved = trigger
				? await updateTrigger(trigger.id, payload)
				: await createTrigger({ ...payload, isActive: true });
			onSaved(saved);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save the trigger."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleCancel = () => {
		if (isDirty && !confirm("Discard unsaved changes?")) {
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
					onCancel={onCancel ? handleCancel : undefined}
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
										className="w-full flex-1 resize-none border-none bg-transparent font-mono text-[12.5px] leading-[1.7] text-foreground placeholder:text-meta dark:placeholder:text-panel-dim focus:outline-none [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
									/>
									<div className="mt-4 flex shrink-0 items-center border-t border-hairline pt-3.5 dark:border-white/5">
										<ModelPickerChip
											value={form.modelId}
											onChange={(modelId) => {
												setField("modelId", modelId);
											}}
											unavailable={
												trigger && form.modelId === trigger.modelId
													? !trigger.modelAvailable
													: undefined
											}
											unavailableLabel={
												trigger && form.modelId === trigger.modelId
													? trigger.modelDisplayName
													: undefined
											}
										/>
									</div>
								</div>
							</EditorSection>
						</div>

						{/* Right: frequency card with embedded next-runs preview */}
						<div className="flex w-full flex-col gap-7 md:w-1/2">
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
										/>
									</div>
									<div className="border-t border-hairline px-4.5 pt-2.5 pb-1.5 dark:border-white/5">
										<div className="px-0.5 pb-1 font-mono text-[10.5px] font-semibold uppercase tracking-[0.09em] text-meta dark:text-panel-dim">
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
						</div>
					</div>
				</div>
			</div>
		</div>
	);
}

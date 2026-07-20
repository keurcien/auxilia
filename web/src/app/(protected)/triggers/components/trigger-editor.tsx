"use client";

import { useEffect, useMemo, useState } from "react";
import { AlarmClock } from "lucide-react";
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
import { EditorHeader } from "@/components/editor/editor-header";
import { EditorSection } from "@/components/editor/editor-section";
import { SaveActions } from "@/components/editor/save-actions";
import { AgentPicker } from "@/components/editor/agent-picker";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";
import ScheduleBuilder from "@/app/(protected)/triggers/components/schedule-builder";
import NextRunsCard from "@/app/(protected)/triggers/components/next-runs-card";

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
		<div className="flex flex-col font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
			<EditorHeader
				icon={<AlarmClock className="size-[23px]" />}
				iconClassName="bg-[#E6F2EB] dark:bg-emerald-950/40 text-[#2F7F57] dark:text-emerald-400"
				title={trigger ? "Edit trigger" : "New trigger"}
				subtitle={
					trigger ? (
						<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px] font-medium text-[#94A59D] dark:text-muted-foreground">
							{trigger.name}
						</span>
					) : undefined
				}
				actions={
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
				}
			/>

			{error && (
				<div className="mt-5 rounded-[14px] bg-[#FFF5F3] dark:bg-[#D45B45]/10 px-4 py-3 text-[13.5px] font-medium text-[#D45B45]">
					{error}
				</div>
			)}

			<div className="flex flex-col md:flex-row gap-8 mt-7">
				{/* Left: name, agent, instructions */}
				<div className="flex flex-col gap-7 flex-1 min-w-0">
					<EditorSection label="Trigger name">
						<input
							type="text"
							maxLength={255}
							value={form.name}
							onChange={(e) => {
								setField("name", e.target.value);
							}}
							placeholder="What does this trigger do?"
							className="w-full px-[17px] py-[15px] rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card text-[15px] font-semibold text-[#1E2D28] dark:text-white leading-[1.5] placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 shadow-[0_1px_3px_rgba(33,36,31,0.04)] focus:outline-none focus:border-[#4CA882] transition-colors"
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
						<div className="flex flex-col flex-1 min-h-[300px] rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card p-[18px] shadow-[0_1px_3px_rgba(33,36,31,0.04)] focus-within:border-[#4CA882] transition-colors">
							<textarea
								value={form.instructions}
								onChange={(e) => {
									setField("instructions", e.target.value);
								}}
								placeholder="The message sent to the agent on every run..."
								className="flex-1 w-full resize-none bg-transparent border-none text-[14.5px] font-medium text-[#3A4A43] dark:text-white leading-[1.6] placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 focus:outline-none [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
							/>
							<div className="flex items-center shrink-0 mt-4 pt-3.5 border-t border-[#edf2ef] dark:border-white/5">
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
				<div className="flex flex-col gap-7 w-full md:w-1/2">
					<EditorSection label="Frequency">
						<div className="flex flex-col rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)]">
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
							<div className="border-t border-[#F1F5F3] dark:border-white/5 px-4.5 pt-2.5 pb-1.5">
								<div className="px-0.5 pb-1 font-[family-name:var(--font-dm-sans)] text-[10.5px] font-semibold uppercase tracking-[0.1em] text-[#AEBBB4] dark:text-muted-foreground">
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
	);
}

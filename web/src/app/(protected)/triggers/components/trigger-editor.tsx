"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
import { useProjectsStore } from "@/stores/projects-store";
import { CodeBlock } from "@/components/ai-elements/code-block";
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
import {
	AsyncSearchSelect,
	type AsyncSearchOption,
} from "@/components/ui/async-search-select";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import type { ResourceVisibility } from "@/types/visibility";
import { groupOptions } from "@/lib/groups";
import { getProjectFolderPath } from "@/lib/project-folders";
import * as projectsApi from "@/lib/api/resources/projects";
import { PETROL_MONO_THEME } from "@/lib/shiki-petrol-mono";
import ScheduleBuilder from "@/app/(protected)/triggers/components/schedule-builder";
import NextRunsCard from "@/app/(protected)/triggers/components/next-runs-card";
import TriggerResources from "@/app/(protected)/triggers/components/trigger-resources";

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
	projectId: string | null;
	folderId: string | null;
	disabledMcpServerIds: string[] | null;
	disabledSkillIds: string[] | null;
	disabledSandboxIds: string[] | null;
	disabledSubagentIds: string[] | null;
	disabledMcpTools: Record<string, string[]> | null;
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
		projectId: null,
		folderId: null,
		disabledMcpServerIds: null,
		disabledSkillIds: null,
		disabledSandboxIds: null,
		disabledSubagentIds: null,
		disabledMcpTools: null,
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
		projectId: trigger.projectId,
		folderId: trigger.folderId,
		disabledMcpServerIds: trigger.disabledMcpServerIds,
		disabledSkillIds: trigger.disabledSkillIds,
		disabledSandboxIds: trigger.disabledSandboxIds,
		disabledSubagentIds: trigger.disabledSubagentIds,
		disabledMcpTools: trigger.disabledMcpTools,
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
		projectId: form.projectId,
		folderId: form.folderId,
		disabledMcpServerIds: form.disabledMcpServerIds,
		disabledSkillIds: form.disabledSkillIds,
		disabledSandboxIds: form.disabledSandboxIds,
		disabledSubagentIds: form.disabledSubagentIds,
		disabledMcpTools: form.disabledMcpTools,
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
	initialRightTab?: "frequency" | "resources";
	onRightTabChange?: (tab: "frequency" | "resources") => void;
}

export default function TriggerEditor({
	trigger,
	triggerType,
	onSaved,
	onCancel,
	initialRightTab = "frequency",
	onRightTabChange,
}: TriggerEditorProps) {
	const createTrigger = useTriggersStore((state) => state.createTrigger);
	const updateTrigger = useTriggersStore((state) => state.updateTrigger);
	const triggers = useTriggersStore((state) => state.triggers);
	const fetchTriggers = useTriggersStore((state) => state.fetchTriggers);
	const models = useModelsStore((state) => state.models);
	const projects = useProjectsStore((state) => state.projects);
	const projectTree = useProjectsStore((state) => state.tree);
	const fetchProjects = useProjectsStore((state) => state.fetchProjects);
	const confirmDialog = useConfirmDialog();
	const type = trigger?.triggerType ?? triggerType ?? "schedule";

	const initialForm = useMemo(
		() => (trigger ? fromTrigger(trigger) : defaultForm()),
		[trigger],
	);
	const [form, setForm] = useState<TriggerFormState>(initialForm);
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [rightTab, setRightTab] = useState<"frequency" | "resources">(
		initialRightTab,
	);
	const availableGroups = useMemo(() => groupOptions(triggers), [triggers]);

	useEffect(() => {
		fetchTriggers().catch(() => {});
		void fetchProjects().catch(() => {});
	}, [fetchProjects, fetchTriggers]);

	const setField = <K extends keyof TriggerFormState>(
		key: K,
		value: TriggerFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const selectedModelId =
		form.modelId ?? (trigger ? null : (getDefaultModel(models) ?? null));

	const cronExpression = buildCronExpression(form.schedule);
	const selectedProject = projects.find(
		(project) => project.id === form.projectId,
	);
	const projectFolders =
		projectTree.find((project) => project.id === form.projectId)?.folders ?? [];
	const selectedFolder = projectFolders.find(
		(folder) => folder.id === form.folderId,
	);
	const selectedProjectOption: AsyncSearchOption | null = selectedProject
		? {
				value: selectedProject.id,
				label: selectedProject.emoji
					? `${selectedProject.emoji} ${selectedProject.name}`
					: selectedProject.name,
				description: selectedProject.description || undefined,
			}
		: null;
	const selectedFolderOption: AsyncSearchOption | null = selectedFolder
		? {
				value: selectedFolder.id,
				label: getProjectFolderPath(selectedFolder, projectFolders),
			}
		: null;
	const loadProjectOptions = useCallback(
		async (query: string, signal: AbortSignal) =>
			(await projectsApi.searchProjects(query, signal)).map((project) => ({
				value: project.id,
				label: project.emoji
					? `${project.emoji} ${project.name}`
					: project.name,
				description: project.description || undefined,
			})),
		[],
	);
	const loadFolderOptions = useCallback(
		async (query: string, signal: AbortSignal) => {
			if (!form.projectId) return [];
			return (
				await projectsApi.searchProjectFolders(form.projectId, query, signal)
			).map((folder) => ({
				value: folder.id,
				label: folder.path,
			}));
		},
		[form.projectId],
	);
	const isDirty =
		JSON.stringify(toComparablePayload(form, type)) !==
		JSON.stringify(toComparablePayload(initialForm, type));
	const canSave = Boolean(
		form.name.trim() &&
		form.instructions.trim() &&
		form.agentId &&
		selectedModelId &&
		(type === "webhook" || cronExpression) &&
		(form.projectId !== null ||
			form.visibility !== "teams" ||
			form.teamIds.length > 0),
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
			projectId: form.projectId,
			folderId: form.folderId,
			...(form.projectId === null
				? { visibility: form.visibility, teamIds: form.teamIds }
				: {}),
			disabledMcpServerIds: form.disabledMcpServerIds,
			disabledSkillIds: form.disabledSkillIds,
			disabledSandboxIds: form.disabledSandboxIds,
			disabledSubagentIds: form.disabledSubagentIds,
			disabledMcpTools: form.disabledMcpTools,
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

			<div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				{/* Left: trigger definition */}
				<div className="flex min-w-0 shrink-0 flex-col gap-7 border-b border-border bg-background px-4 py-7 sm:px-7 md:flex-[1.05] md:shrink md:overflow-y-auto md:border-r md:border-b-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{error && (
						<div className="rounded-[10px] bg-destructive/10 px-4 py-3 text-[13.5px] font-medium text-destructive">
							{error}
						</div>
					)}

					<EditorSection label="Trigger name">
						<input
							type="text"
							autoFocus={!trigger}
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
					<div className="grid gap-3 sm:grid-cols-2">
						<AsyncSearchSelect
							label="Project"
							value={form.projectId}
							selectedOption={selectedProjectOption}
							placeholder="Search projects"
							emptyValueLabel="No project"
							loadOptions={loadProjectOptions}
							onChange={(projectId) => {
								setForm((current) => ({
									...current,
									projectId,
									folderId: null,
								}));
							}}
						/>
						<AsyncSearchSelect
							label="Folder"
							value={form.folderId}
							selectedOption={selectedFolderOption}
							placeholder="Search folders"
							emptyValueLabel="Project root"
							disabled={form.projectId === null}
							loadOptions={loadFolderOptions}
							onChange={(folderId) => {
								setField("folderId", folderId);
							}}
						/>
					</div>
					{selectedProject ? (
						<p className="rounded-[8px] bg-petrol-tint px-3 py-2 text-[11.5px] leading-5 text-petrol dark:bg-white/5 dark:text-panel-dim">
							Access is inherited from {selectedProject.name} (
							{selectedProject.visibility === "teams"
								? "selected teams"
								: selectedProject.visibility}
							).
						</p>
					) : (
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
					)}

					<EditorSection label="Agent">
						<AgentPicker
							value={form.agentId}
							onChange={(agentId) => {
								setForm((current) => ({
									...current,
									agentId,
									disabledMcpServerIds: null,
									disabledSkillIds: null,
									disabledSandboxIds: null,
									disabledSubagentIds: null,
									disabledMcpTools: null,
								}));
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

				{/* Right: launch configuration and inherited resources */}
				<div className="min-w-0 shrink-0 bg-sidebar px-4 py-7 sm:px-7 md:flex-1 md:shrink md:overflow-y-auto dark:bg-white/[0.02] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<UnderlineTabs
						tabs={[
							{
								key: "frequency",
								label: type === "schedule" ? "Frequency" : "Webhook",
							},
							{ key: "resources", label: "Resources" },
						]}
						value={rightTab}
						onChange={(tab) => {
							setRightTab(tab);
							onRightTabChange?.(tab);
						}}
						className="border-b border-border"
					/>

					<div className="pt-5">
						{rightTab === "resources" ? (
							<TriggerResources
								agentId={form.agentId}
								disabledMcpServerIds={form.disabledMcpServerIds}
								disabledSkillIds={form.disabledSkillIds}
								disabledSandboxIds={form.disabledSandboxIds}
								disabledSubagentIds={form.disabledSubagentIds}
								disabledMcpTools={form.disabledMcpTools}
								onDisabledMcpServerIdsChange={(ids) => {
									setField("disabledMcpServerIds", ids);
								}}
								onDisabledSkillIdsChange={(ids) => {
									setField("disabledSkillIds", ids);
								}}
								onDisabledSandboxIdsChange={(ids) => {
									setField("disabledSandboxIds", ids);
								}}
								onDisabledSubagentIdsChange={(ids) => {
									setField("disabledSubagentIds", ids);
								}}
								onDisabledMcpToolsChange={(tools) => {
									setField("disabledMcpTools", tools);
								}}
							/>
						) : type === "schedule" ? (
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
						) : (
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
											Each POST starts a fresh thread. You can copy the endpoint
											after creating the trigger.
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
									<CodeBlock
										code={`{
  "agent_id": "uuid",
  "model_id": "provider/model",
  "instructions": "Run-specific prompt"
}`}
										language="json"
										theme={PETROL_MONO_THEME}
										className="bg-panel"
									/>
									<p className="mt-3 text-[11.5px] leading-5 text-meta dark:text-panel-dim">
										Any omitted value falls back to this trigger&apos;s
										configuration.
									</p>
								</div>
							</div>
						)}
					</div>
				</div>
			</div>
		</div>
	);
}

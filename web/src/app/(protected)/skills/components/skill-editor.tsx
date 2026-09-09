"use client";

import { useEffect, useMemo, useState } from "react";
import { Download, Trash2 } from "lucide-react";
import { MessageResponse } from "@/components/ai-elements/message";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import {
	HeaderButton,
	HeaderPrimaryButton,
	SubpageHeader,
	UnsavedBadge,
} from "@/components/layout/subpage-header";
import { API_BASE_URL } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { useSkillsStore } from "@/stores/skills-store";
import type { Skill, SkillFile } from "@/types/skills";
import {
	composeSkillMarkdown,
	skillDescriptionError,
	skillNameError,
	splitSkillMarkdown,
} from "../lib/skill-form";
import SkillFilesPanel, { skillFilePathError } from "./skill-files-panel";

type EditorTab = "instructions" | "raw";

const NEW_SKILL = composeSkillMarkdown({
	name: "",
	description: "",
	extra: [],
	body: "# When to use\n\n# Steps\n\n1. \n",
});

interface SkillEditorProps {
	/** Undefined = create mode (`/skills/new`). */
	skill?: Skill;
	/** Read mode — the document renders as markdown, nothing is editable. */
	readOnly?: boolean;
	/** Provided in read mode when the viewer may edit — shows the Edit button. */
	onEdit?: () => void;
	onSaved: (skill: Skill) => void;
	/** Discard/Cancel: back to read mode (detail) or leave the page (create). */
	onCancel: () => void;
	onDeleted?: () => void;
}

interface Draft {
	content: string;
	files: SkillFile[];
}

/**
 * The skill editor. The draft *is* the SKILL.md document plus its files —
 * exactly what the API stores — and the name / description / body inputs
 * are a view over that document (`splitSkillMarkdown`). A document whose
 * frontmatter cannot be round-tripped through those inputs is edited raw.
 */
export default function SkillEditor({
	skill,
	readOnly = false,
	onEdit,
	onSaved,
	onCancel,
	onDeleted,
}: SkillEditorProps) {
	const createSkill = useSkillsStore((state) => state.createSkill);
	const updateSkill = useSkillsStore((state) => state.updateSkill);
	const deleteSkill = useSkillsStore((state) => state.deleteSkill);

	const initial = useMemo<Draft>(
		() =>
			skill
				? { content: skill.content, files: skill.files }
				: { content: NEW_SKILL, files: [] },
		[skill],
	);
	const [draft, setDraft] = useState<Draft>(initial);
	const fields = useMemo(() => splitSkillMarkdown(draft.content), [draft.content]);
	// A document the form cannot represent is edited as raw text only.
	const rawOnly = fields === null;
	const [tab, setTab] = useState<EditorTab>(rawOnly ? "raw" : "instructions");
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const isDirty = !readOnly && JSON.stringify(draft) !== JSON.stringify(initial);
	const name = fields?.name ?? skill?.name ?? "";
	const description = fields?.description ?? skill?.description ?? "";

	const setFields = (patch: Partial<NonNullable<typeof fields>>) => {
		if (!fields) return;
		setDraft((prev) => ({
			...prev,
			content: composeSkillMarkdown({ ...fields, ...patch }),
		}));
	};

	const nameError = fields ? skillNameError(fields.name) : null;
	const descriptionError = fields ? skillDescriptionError(fields.description) : null;
	const bodyError = fields && !fields.body.trim() ? "Instructions are required" : null;
	const filesValid = draft.files.every(
		(file, i) =>
			skillFilePathError(
				file.path,
				draft.files.filter((_, j) => j !== i).map((f) => f.path),
			) === null,
	);
	const canSave =
		filesValid &&
		draft.content.trim().length > 0 &&
		!nameError &&
		!descriptionError &&
		!bodyError;

	useEffect(() => {
		if (!isDirty) return;
		const warn = (event: BeforeUnloadEvent) => {
			event.preventDefault();
		};
		window.addEventListener("beforeunload", warn);
		return () => {
			window.removeEventListener("beforeunload", warn);
		};
	}, [isDirty]);

	const handleSave = async () => {
		if (!canSave) return;
		setIsSaving(true);
		setError(null);
		try {
			const saved = skill
				? await updateSkill(skill.id, { ...draft, revision: skill.revision })
				: await createSkill(draft);
			onSaved(saved);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save the skill."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleCancel = () => {
		if (isDirty && !confirm("Discard unsaved changes?")) return;
		onCancel();
	};

	const handleDelete = async () => {
		if (!skill || !confirm(`Delete the skill "${skill.name}"?`)) return;
		setError(null);
		try {
			await deleteSkill(skill.id);
			onDeleted?.();
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to delete the skill."));
		}
	};

	const fieldInputClass =
		"w-full rounded-lg border border-input bg-card px-3 py-[7px] outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default";
	const editorClass =
		"min-h-[300px] w-full flex-1 resize-none rounded-lg border border-input bg-sidebar p-4 font-mono text-[12.5px] leading-[1.7] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] [scrollbar-width:thin]";

	const tabs: { key: EditorTab; label: string }[] = [
		...(rawOnly ? [] : [{ key: "instructions" as const, label: "Instructions" }]),
		{ key: "raw", label: "SKILL.md" },
	];

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={[
					{ label: "workspace" },
					{ label: "skills", href: "/skills" },
					{ label: name || (skill ? skill.name : "new") },
				]}
				badge={isDirty ? <UnsavedBadge /> : undefined}
			>
				{readOnly && onEdit && (
					<HeaderPrimaryButton onClick={onEdit}>Edit</HeaderPrimaryButton>
				)}
				{!readOnly && (
					<>
						<HeaderButton disabled={isSaving} onClick={handleCancel}>
							{skill ? "Discard" : "Cancel"}
						</HeaderButton>
						<HeaderPrimaryButton
							disabled={isSaving || !canSave || Boolean(skill && !isDirty)}
							onClick={() => {
								void handleSave();
							}}
						>
							{isSaving ? "Saving…" : skill ? "Save changes" : "Create skill"}
						</HeaderPrimaryButton>
					</>
				)}
				{skill && (
					<DropdownMenu
						items={[
							{
								label: "Export as zip",
								icon: <Download />,
								onClick: () => {
									window.location.assign(`${API_BASE_URL}/skills/${skill.id}/export`);
								},
							},
							...(skill.canEdit
								? [
										{ separator: true as const },
										{
											label: "Delete skill",
											icon: <Trash2 />,
											destructive: true,
											onClick: () => {
												void handleDelete();
											},
										},
									]
								: []),
						]}
					/>
				)}
			</SubpageHeader>

			{error && (
				<div className="mx-7 mt-4 shrink-0 rounded-md bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
					{error}
				</div>
			)}

			<div className="flex min-h-0 flex-1 flex-col md:flex-row">
				{/* Left: the document */}
				<div className="flex min-w-0 flex-col overflow-y-auto border-b border-border bg-background p-7 md:flex-[1.05] md:border-b-0 md:border-r [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{readOnly || rawOnly ? (
						<div className="min-w-0">
							<h1 className="truncate py-[2px] font-mono text-[19px] font-semibold tracking-[-0.01em] text-petrol">
								{name || "untitled"}
							</h1>
							<p className="py-[2px] text-[13.5px] font-medium text-label dark:text-muted-foreground">
								{description || " "}
							</p>
							{rawOnly && !readOnly && (
								<p className="mt-2 text-[12px] text-meta dark:text-panel-dim">
									This SKILL.md uses frontmatter the form cannot edit safely, so
									it is edited as a file.
								</p>
							)}
						</div>
					) : (
						<div className="flex min-w-0 flex-col gap-1.5">
							<input
								type="text"
								maxLength={64}
								value={fields?.name ?? ""}
								spellCheck={false}
								onChange={(e) => {
									setFields({ name: e.target.value.trim().toLowerCase() });
								}}
								placeholder="skill-name"
								className={cn(
									fieldInputClass,
									"font-mono text-[15px] font-semibold tracking-[-0.01em] text-petrol",
									nameError && fields?.name && "border-destructive",
								)}
							/>
							<input
								type="text"
								maxLength={1024}
								value={fields?.description ?? ""}
								onChange={(e) => {
									setFields({ description: e.target.value });
								}}
								placeholder="What the skill does and when to use it — this is how agents decide to pick it"
								className={cn(fieldInputClass, "text-[13px] font-medium text-body dark:text-panel-body")}
							/>
							{(nameError && fields?.name) || descriptionError ? (
								<p className="text-[11.5px] text-destructive">
									{(fields?.name && nameError) || descriptionError}
								</p>
							) : null}
						</div>
					)}

					<UnderlineTabs
						tabs={tabs}
						value={rawOnly ? "raw" : tab}
						onChange={setTab}
						className="mt-6 border-b border-border"
					/>

					<div className="flex min-h-0 flex-1 flex-col pt-5">
						{tab === "instructions" && !rawOnly ? (
							readOnly ? (
								<div className="min-h-[200px] w-full flex-1 overflow-y-auto rounded-lg border border-border bg-sidebar p-4 [scrollbar-width:thin]">
									<MessageResponse className="text-[13px] leading-[1.65] text-foreground">
										{fields?.body.trim() || "*No instructions*"}
									</MessageResponse>
								</div>
							) : (
								<textarea
									value={fields?.body ?? ""}
									onChange={(e) => {
										setFields({ body: e.target.value });
									}}
									placeholder="The procedure the agent follows once it picks this skill…"
									className={editorClass}
								/>
							)
						) : (
							<textarea
								value={draft.content}
								readOnly={readOnly}
								spellCheck={false}
								onChange={(e) => {
									setDraft((prev) => ({ ...prev, content: e.target.value }));
								}}
								className={editorClass}
							/>
						)}
					</div>
				</div>

				{/* Right: supporting files */}
				<div className="flex min-w-0 flex-col overflow-y-auto bg-sidebar p-7 md:flex-1 dark:bg-white/[0.02] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<SkillFilesPanel
						files={draft.files}
						readOnly={readOnly}
						onChange={(files) => {
							setDraft((prev) => ({ ...prev, files }));
						}}
					/>
				</div>
			</div>
		</div>
	);
}

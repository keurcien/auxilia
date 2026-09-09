"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { BookOpen, Download, Trash2 } from "lucide-react";
import { Skill } from "@/types/skills";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { MessageResponse } from "@/components/ai-elements/message";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import SkillFilesPanel from "./components/skill-files-panel";
import {
	SkillFormState,
	composeSkillMarkdown,
	defaultSkillForm,
	fromSkill,
	isFormDirty,
	isValidSkillName,
	toPayload,
} from "./lib/skill-form";

type EditorTab = "instructions" | "markdown";

interface SkillEditorProps {
	/** Undefined = create mode (`/skills/new`). */
	skill?: Skill;
	/** Read mode — inputs render disabled, instructions as markdown. */
	readOnly?: boolean;
	/** Provided in read mode when the viewer may edit — shows the Edit button. */
	onEdit?: () => void;
	onSaved: (skill: Skill) => void;
	/** Discard/Cancel: back to read mode (detail) or leave the page (create). */
	onCancel: () => void;
}

const fieldInputClass =
	"w-full rounded-lg border border-input bg-card px-3 py-[7px] outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default";

export default function SkillEditor({
	skill,
	readOnly = false,
	onEdit,
	onSaved,
	onCancel,
}: SkillEditorProps) {
	const router = useRouter();

	// Snapshot taken on mount — the dirty baseline. Re-derives when the
	// skill is saved, never from form edits.
	const initialForm = useMemo(
		() => (skill ? fromSkill(skill) : defaultSkillForm()),
		[skill],
	);
	const [form, setForm] = useState<SkillFormState>(initialForm);
	const [tab, setTab] = useState<EditorTab>("instructions");
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const setField = <K extends keyof SkillFormState>(
		key: K,
		value: SkillFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const isDirty = !readOnly && isFormDirty(form, initialForm);
	const nameValid = isValidSkillName(form.name);
	const canSave = Boolean(
		nameValid && form.description.trim() && form.instructions.trim(),
	);
	const canManage = !skill || skill.canEdit;

	const tabs: { key: EditorTab; label: string }[] = [
		{ key: "instructions", label: "Instructions" },
		{ key: "markdown", label: "SKILL.md" },
	];

	// Warn before leaving the page with unsaved changes.
	useEffect(() => {
		if (!isDirty) return;
		const handleBeforeUnload = (event: BeforeUnloadEvent) => {
			event.preventDefault();
		};
		window.addEventListener("beforeunload", handleBeforeUnload);
		return () => {
			window.removeEventListener("beforeunload", handleBeforeUnload);
		};
	}, [isDirty]);

	const handleSave = async () => {
		if (!canSave) return;
		setIsSaving(true);
		setError(null);
		try {
			const response = skill
				? await api.put<Skill>(
						`/skills/${skill.id}`,
						toPayload(form, skill.revision),
					)
				: await api.post<Skill>("/skills", toPayload(form));
			onSaved(response.data);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save the skill."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleDiscard = () => {
		if (isDirty && !confirm("Discard unsaved changes?")) return;
		onCancel();
	};

	const handleExport = async () => {
		if (!skill) return;
		try {
			const response = await api.get<Blob>(`/skills/${skill.id}/export`, {
				responseType: "blob",
			});
			const url = URL.createObjectURL(response.data);
			const anchor = document.createElement("a");
			anchor.href = url;
			anchor.download = `${skill.name}.zip`;
			anchor.click();
			URL.revokeObjectURL(url);
		} catch (err) {
			setError(getApiErrorMessage(err, "Export failed."));
		}
	};

	const handleDelete = async () => {
		if (!skill) return;
		if (
			!confirm(
				"Delete this skill? Detach it from every agent first if it is still enabled.",
			)
		)
			return;
		try {
			await api.delete(`/skills/${skill.id}`);
			router.push("/skills");
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to delete the skill."));
		}
	};

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			{/* Header bar */}
			<header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border pl-14 pr-4 md:px-7">
				<span className="min-w-0 truncate font-mono text-[11.5px] text-meta dark:text-panel-dim">
					<Link
						href="/skills"
						className="transition-colors hover:text-foreground"
					>
						skills
					</Link>{" "}
					<span className="text-ghost dark:text-panel-dim">/</span>{" "}
					<span className="font-medium text-foreground">
						{form.name.trim() || "…"}
					</span>
				</span>
				{isDirty && (
					<span className="rounded-[4px] bg-warning-bg px-2 py-0.5 font-mono text-[10px] font-semibold tracking-[0.05em] text-warning">
						UNSAVED
					</span>
				)}
				<div className="ml-auto flex shrink-0 items-center gap-2">
					{readOnly && onEdit && (
						<button
							type="button"
							onClick={onEdit}
							className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
						>
							Edit
						</button>
					)}
					{!readOnly && (
						<>
							<button
								type="button"
								disabled={isSaving}
								onClick={handleDiscard}
								className="cursor-pointer rounded-[7px] border border-input bg-card px-4 py-2 text-[13px] font-semibold text-foreground transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50"
							>
								{skill ? "Discard" : "Cancel"}
							</button>
							<button
								type="button"
								disabled={isSaving || !canSave || Boolean(skill && !isDirty)}
								onClick={() => {
									void handleSave();
								}}
								className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
							>
								{isSaving
									? "Saving…"
									: skill
										? "Save changes"
										: "Create skill"}
							</button>
						</>
					)}
					{skill && (
						<DropdownMenu
							items={[
								{
									label: "Export bundle (.zip)",
									icon: <Download />,
									onClick: () => {
										void handleExport();
									},
								},
								...(canManage
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
				</div>
			</header>

			{error && (
				<div className="mx-7 mt-4 shrink-0 rounded-md bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
					{error}
				</div>
			)}

			{/* Two panels: definition left, files right */}
			<div className="flex min-h-0 flex-1 flex-col md:flex-row">
				{/* Left: identity + tabs */}
				<div className="flex min-w-0 flex-col overflow-y-auto border-b border-border bg-background p-7 md:flex-[1.05] md:border-b-0 md:border-r [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<div
						className={cn(
							"flex gap-3.5",
							readOnly ? "items-center" : "items-start",
						)}
					>
						<div className="flex size-12 shrink-0 items-center justify-center rounded-[10px] bg-petrol/10 text-petrol shadow-[inset_0_0_0_1px_rgba(16,24,32,0.06)]">
							<BookOpen className="size-5" />
						</div>
						{readOnly ? (
							<div className="min-w-0 flex-1">
								<h1 className="w-full truncate py-[2px] font-mono text-[19px] font-semibold tracking-[-0.01em] text-petrol">
									{form.name}
								</h1>
								<p className="w-full truncate py-[2px] text-[13.5px] font-medium text-label dark:text-muted-foreground">
									{form.description || " "}
								</p>
							</div>
						) : (
							<div className="flex min-w-0 flex-1 flex-col gap-1.5">
								<input
									type="text"
									maxLength={64}
									value={form.name}
									autoCapitalize="off"
									autoCorrect="off"
									spellCheck={false}
									onChange={(e) => {
										setField("name", e.target.value);
									}}
									placeholder="skill-name"
									aria-invalid={form.name.length > 0 && !nameValid}
									className={cn(
										fieldInputClass,
										"font-mono text-[15px] font-semibold tracking-[-0.01em] text-petrol",
										form.name.length > 0 &&
											!nameValid &&
											"border-destructive focus:border-destructive focus:shadow-[0_0_0_3px_rgba(220,38,38,0.10)]",
									)}
								/>
								<input
									type="text"
									maxLength={1024}
									value={form.description}
									onChange={(e) => {
										setField("description", e.target.value);
									}}
									placeholder="When should the agent use this skill?"
									className={cn(
										fieldInputClass,
										"text-[13px] font-medium text-body dark:text-panel-body",
									)}
								/>
								<p className="font-mono text-[11px] text-meta dark:text-panel-dim">
									{form.name.length > 0 && !nameValid
										? "Lowercase letters, digits and single hyphens only, e.g. pdf-tools"
										: "Name and description become the SKILL.md frontmatter."}
								</p>
							</div>
						)}
					</div>

					<UnderlineTabs
						tabs={tabs}
						value={tab}
						onChange={setTab}
						className="mt-6 border-b border-border"
					/>

					<div className="flex min-h-0 flex-1 flex-col pt-5">
						{tab === "instructions" &&
							(readOnly ? (
								<div className="min-h-[200px] w-full flex-1 overflow-y-auto rounded-lg border border-border bg-sidebar p-4 [scrollbar-width:thin]">
									{form.instructions ? (
										<MessageResponse className="text-[13px] leading-[1.65] text-foreground">
											{form.instructions}
										</MessageResponse>
									) : (
										<p className="text-[13px] text-meta dark:text-panel-dim">
											No instructions
										</p>
									)}
								</div>
							) : (
								<textarea
									value={form.instructions}
									onChange={(e) => {
										setField("instructions", e.target.value);
									}}
									placeholder="Describe the procedure the agent should follow. Reference files by their path, e.g. scripts/check.py…"
									className="min-h-[300px] w-full flex-1 resize-none rounded-lg border border-input bg-sidebar p-4 font-mono text-[12.5px] leading-[1.7] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] [scrollbar-width:thin]"
								/>
							))}
						{tab === "markdown" && (
							<pre className="min-h-[200px] w-full flex-1 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-sidebar p-4 font-mono text-[12.5px] leading-[1.7] text-foreground [scrollbar-width:thin]">
								{composeSkillMarkdown(form)}
							</pre>
						)}
					</div>
				</div>

				{/* Right: supporting files */}
				<div className="flex min-w-0 flex-col overflow-y-auto bg-sidebar p-7 md:flex-1 dark:bg-white/[0.02] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<SkillFilesPanel
						files={form.files}
						readOnly={readOnly}
						busy={isSaving}
						onChange={(update) => {
							setForm((prev) => ({ ...prev, files: update(prev.files) }));
						}}
						onError={setError}
					/>
				</div>
			</div>
		</div>
	);
}

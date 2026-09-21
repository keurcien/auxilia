"use client";

import { cloneElement, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
	CircleAlert,
	FileText,
	GitCompareArrows,
	TerminalSquare,
	Trash2,
	TriangleAlert,
	Unplug,
} from "lucide-react";
import { MessageResponse } from "@/components/ai-elements/message";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import {
	HeaderButton,
	HeaderPrimaryButton,
	HeaderReadOnly,
	SubpageHeader,
	UnsavedBadge,
} from "@/components/layout/subpage-header";
import { getApiErrorMessage } from "@/lib/api/errors";
import { SkillDeleteDescription } from "./skill-delete-description";
import { cn } from "@/lib/utils";
import { useSkillsStore } from "@/stores/skills-store";
import {
	countScripts,
	isDetached,
	isSourced,
	repoLabel,
	shortRevision,
	type Skill,
	type SkillFile,
} from "@/types/skills";
import {
	composeSkillMarkdown,
	skillBody,
	skillDescriptionError,
	skillNameError,
	splitSkillMarkdown,
} from "../lib/skill-form";
import { useDeleteSkill } from "../lib/use-delete-skill";
import SkillDiffDialog from "./skill-diff-dialog";
import SkillFilesPanel from "./skill-files-panel";
import SkillInUseDialog from "./skill-in-use-dialog";
import SkillUsedBy from "./skill-used-by";

type NoticeTone = "plain" | "warning" | "alert";

const NOTICE_TONE: Record<NoticeTone, { box: string; icon: string }> = {
	plain: {
		box: "border-input bg-petrol-tint text-body dark:border-white/10 dark:bg-white/[0.04] dark:text-panel-body",
		icon: "text-petrol",
	},
	warning: {
		box: "border-[#F0DCC2] bg-[#FDF9F0] text-[#7A5C1E] dark:border-[#7A5C1E]/40 dark:bg-[#7A5C1E]/10 dark:text-[#E8C27A]",
		icon: "text-[#B98B2E] dark:text-[#E8C27A]",
	},
	alert: {
		box: "border-destructive/20 bg-destructive/10 text-destructive",
		icon: "text-destructive",
	},
};

/**
 * Everything the editor has to say about the skill it is showing, in one
 * shape: an icon and a line, inside the definition panel.
 *
 * These used to be full-width banners stacked above the two panels, so each
 * one pushed the layout down and the editor started lower the more there was
 * to say — with the panels themselves reflowing as a skill's state changed.
 * Inside the panel they read as notes about the definition, which is what
 * they are, and the two-column layout stays put.
 */
function EditorNotice({
	icon,
	tone = "plain",
	children,
}: {
	icon: React.ReactElement<{ className?: string }>;
	tone?: NoticeTone;
	children: React.ReactNode;
}) {
	const style = NOTICE_TONE[tone];
	return (
		<div
			className={cn(
				"mt-5 flex shrink-0 items-start gap-2.5 rounded-[7px] border px-3.5 py-2.5",
				style.box,
			)}
		>
			{cloneElement(icon, { className: cn("mt-px size-3.5 shrink-0", style.icon) })}
			<span className="min-w-0 text-[12.5px] leading-[1.5]">{children}</span>
		</div>
	);
}

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
	/** Open the review-changes dialog on mount (`?review=1` from the library). */
	reviewOnOpen?: boolean;
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
 *
 * Two panels like the agent editor (design 12a): the definition on the
 * left, the files and the agents using the skill on the right. The
 * requirement chip follows the draft, so adding a first script flips it
 * before the save does.
 */
export default function SkillEditor({
	skill,
	readOnly = false,
	onEdit,
	onSaved,
	onCancel,
	onDeleted,
	reviewOnOpen = false,
}: SkillEditorProps) {
	const createSkill = useSkillsStore((state) => state.createSkill);
	const updateSkill = useSkillsStore((state) => state.updateSkill);
	const [reviewOpen, setReviewOpen] = useState(reviewOnOpen && Boolean(skill?.updateAvailable));
	// The repository's, whether or not it is still connected: the files and
	// scripts are in the row either way, so they are shown either way.
	const sourced = skill ? isSourced(skill) : false;
	const detached = skill ? isDetached(skill) : false;

	const initial = useMemo<Draft>(
		() =>
			skill
				? { content: skill.content, files: skill.files }
				: { content: NEW_SKILL, files: [] },
		[skill],
	);
	const [draft, setDraft] = useState<Draft>(initial);
	const fields = useMemo(() => splitSkillMarkdown(draft.content), [draft.content]);
	// The form edits only a flat frontmatter; reading needs just the body.
	const body = useMemo(() => fields?.body ?? skillBody(draft.content), [fields, draft.content]);
	// A document whose frontmatter the form cannot round-trip (a folded
	// scalar, a flow collection) is shown, not edited: export it, edit the
	// file, import it again.
	const locked = fields === null;
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const isDirty = !readOnly && JSON.stringify(draft) !== JSON.stringify(initial);
	const name = fields?.name ?? skill?.name ?? "";
	const description = fields?.description ?? skill?.description ?? "";
	const agents = skill?.agents ?? [];
	const scriptCount = countScripts(draft.files);

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
	const canSave =
		!locked &&
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

	const remove = useDeleteSkill({
		onDeleted: () => {
			onDeleted?.();
		},
		onError: (err) => {
			setError(getApiErrorMessage(err, "Failed to delete the skill."));
		},
	});

	const fieldInputClass =
		"w-full rounded-lg border border-input bg-card px-3 py-[7px] outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default";
	const editorClass =
		"min-h-[300px] w-full flex-1 resize-none rounded-lg border border-input bg-sidebar p-4 font-mono text-[12.5px] leading-[1.7] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] [scrollbar-width:thin]";

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
				{readOnly && skill?.updateAvailable && (
					<HeaderPrimaryButton
						onClick={() => {
							setReviewOpen(true);
						}}
					>
						Review update
					</HeaderPrimaryButton>
				)}
				{readOnly && onEdit && !sourced && (
					<HeaderPrimaryButton onClick={onEdit}>Edit</HeaderPrimaryButton>
				)}
				{readOnly && skill && sourced && (
					<HeaderReadOnly
						title={
							detached
								? `From a repository that is no longer connected${
										skill.sourcePath ? ` · ${skill.sourcePath}` : ""
									} — connect it again to change this skill`
								: `Synced from ${skill.sourceName ?? "a repository"}${
										skill.sourcePath ? ` · ${skill.sourcePath}` : ""
									} — edited in the repository, not here`
						}
					/>
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
							...(skill.updateAvailable
								? [
										{
											label: "Review update",
											icon: <GitCompareArrows />,
											onClick: () => {
												setReviewOpen(true);
											},
										},
									]
								: []),
							...(skill.canManage
								? [
										{ separator: true as const },
										{
											label: "Delete skill",
											icon: <Trash2 />,
											destructive: true,
											onClick: () => {
												setError(null);
												remove.requestDelete(skill);
											},
										},
									]
								: []),
						]}
					/>
				)}
			</SubpageHeader>

			{skill && sourced && (
				<SkillDiffDialog
					open={reviewOpen}
					onOpenChange={setReviewOpen}
					skill={skill}
					canAdopt={skill.canManage}
					onAdopted={onSaved}
				/>
			)}

			{skill && (
				<>
					<SkillInUseDialog
						open={remove.guard !== null}
						onOpenChange={(open) => {
							if (!open) remove.clearGuard();
						}}
						skillName={remove.guard?.skill.name ?? null}
						agents={remove.guard?.agents ?? []}
					/>
					<ConfirmDialog
						open={remove.pending !== null}
						onOpenChange={(open) => {
							if (!open) remove.clearPending();
						}}
						title="Delete this skill?"
						description={<SkillDeleteDescription skill={skill} />}
						confirmLabel="Delete skill"
						destructive
						onConfirm={remove.confirmDelete}
						errorMessage="Could not delete the skill. Please try again."
					/>
				</>
			)}

			<div className="flex min-h-0 flex-1 flex-col md:flex-row">
				{/* Left: definition */}
				<div className="flex min-w-0 flex-col overflow-y-auto border-b border-border bg-background p-7 md:flex-[1.05] md:border-b-0 md:border-r [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<div className="flex min-w-0 items-start gap-4">
						<span className="flex size-12 shrink-0 items-center justify-center rounded-xl border border-input bg-petrol-tint text-petrol dark:border-white/10 dark:bg-white/10">
							<FileText className="size-[22px]" />
						</span>
						{readOnly || locked ? (
							<div className="min-w-0 flex-1">
								<div className="flex min-w-0 flex-wrap items-center gap-2">
									<h1 className="min-w-0 truncate py-[2px] font-mono text-[19px] font-semibold tracking-[-0.01em] text-petrol">
										{name || "untitled"}
									</h1>
									{skill?.updateAvailable && (
										<span className="shrink-0 rounded-[4px] bg-warning-bg px-1.5 py-px font-mono text-[9px] font-semibold tracking-[0.05em] text-warning">
											UPDATE
										</span>
									)}
								</div>
								<p className="py-[2px] text-[13.5px] font-medium text-label dark:text-muted-foreground">
									{description || " "}
								</p>
								{locked && !readOnly && (
									<p className="mt-2 text-[12px] text-warning">
										This SKILL.md uses YAML the editor cannot rewrite safely (a folded or
										multi-line value). Export it, and keep it in a connected repository.
									</p>
								)}
							</div>
						) : (
							<div className="flex min-w-0 flex-1 flex-col gap-1.5">
								<input
									type="text"
									maxLength={64}
									value={fields.name}
									spellCheck={false}
									onChange={(e) => {
										setFields({ name: e.target.value.trim().toLowerCase() });
									}}
									placeholder="skill-name"
									className={cn(
										fieldInputClass,
										"font-mono text-[15px] font-semibold tracking-[-0.01em] text-petrol",
										nameError && fields.name && "border-destructive",
									)}
								/>
								<input
									type="text"
									maxLength={1024}
									value={fields.description}
									onChange={(e) => {
										setFields({ description: e.target.value });
									}}
									placeholder="What the skill does and when to use it — this is how agents decide to pick it"
									className={cn(fieldInputClass, "text-[13px] font-medium text-body dark:text-panel-body")}
								/>
								{/* Rule violations only — an empty required field is what the
								    disabled Create button says, not a red line on a blank form. */}
								{(nameError && fields.name) || (descriptionError && fields.description) ? (
									<p className="text-[11.5px] text-destructive">
										{(fields.name && nameError) || descriptionError}
									</p>
								) : null}
							</div>
						)}
					</div>


					{error && (
						<EditorNotice tone="alert" icon={<CircleAlert />}>
							{error}
						</EditorNotice>
					)}

					{skill && detached && (
						<EditorNotice icon={<Unplug />}>
							{/* The URL, not the word "repository": reconnecting is matched on
							    it, so the one action this suggests needs it spelled out. */}
							<Link href="/skills?view=sources" className="font-semibold text-petrol hover:underline">
								{repoLabel(skill.sourceUrl) || "Its repository"}
							</Link>{" "}
							is no longer connected. The skill keeps running, pinned to{" "}
							<span className="font-mono text-[11.5px]">{shortRevision(skill.sourceRevision)}</span> — connect{" "}
							<span className="font-mono text-[11.5px]">{skill.sourceUrl ?? "the repository"}</span> again to
							change it, and this skill is re-pinned rather than imported a second time. Deleting it from the
							library still works.
						</EditorNotice>
					)}

					{skill && sourced && skill.missingUpstream && (
						<EditorNotice tone="warning" icon={<TriangleAlert />}>
							No longer in{" "}
							<Link href="/skills?view=sources" className="font-semibold underline">
								{skill.sourceName ?? "its repository"}
							</Link>{" "}
							as of the last sync — it keeps working, pinned to{" "}
							<span className="font-mono text-[11.5px]">{shortRevision(skill.sourceRevision)}</span>.
						</EditorNotice>
					)}

					{scriptCount > 0 && (
						<EditorNotice icon={<TerminalSquare />}>
							This skill requires an agent with code execution. Its {scriptCount}{" "}
							script{scriptCount === 1 ? "" : "s"} only run there — the instructions
							apply on any agent.
						</EditorNotice>
					)}

					<div className="mt-6 flex min-h-[24px] shrink-0 items-center justify-between border-b border-border pb-2">
						<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
							INSTRUCTIONS
						</span>
						{!readOnly && !locked && (
							<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
								markdown · name, description and this text make the SKILL.md
							</span>
						)}
					</div>

					<div className="flex min-h-0 flex-1 flex-col pt-4">
						{readOnly || locked ? (
							<div className="min-h-[200px] w-full flex-1 overflow-y-auto rounded-lg border border-border bg-sidebar p-4 [scrollbar-width:thin]">
								<MessageResponse className="text-[13px] leading-[1.65] text-foreground">
									{body?.trim() || "*No instructions*"}
								</MessageResponse>
							</div>
						) : (
							<textarea
								value={fields.body}
								onChange={(e) => {
									setFields({ body: e.target.value });
								}}
								placeholder="The procedure the agent follows once it picks this skill…"
								className={editorClass}
							/>
						)}
					</div>
				</div>

				{/* Right: files (sourced skills only) + where it's used */}
				<div className="flex min-w-0 flex-col overflow-y-auto bg-sidebar p-7 md:flex-1 dark:bg-white/[0.02] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{sourced ? (
						<SkillFilesPanel files={draft.files} skill={skill} />
					) : (
						<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
							A skill written here is one SKILL.md — it runs on any agent.
							<span className="mt-1 block text-[12px]">
								Scripts and reference files come from a{" "}
								<Link href="/skills?view=sources" className="font-semibold text-petrol hover:underline">
									connected repository
								</Link>
								, where they are reviewed and versioned.
							</span>
						</div>
					)}
					{skill && <SkillUsedBy agents={agents} />}
				</div>
			</div>
		</div>
	);
}

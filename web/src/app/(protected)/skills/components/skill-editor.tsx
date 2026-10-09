"use client";

import { cloneElement, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import EmojiPicker, { type EmojiClickData, Theme } from "emoji-picker-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";
import {
	CircleAlert,
	GitCompareArrows,
	Pencil,
	TerminalSquare,
	Trash2,
	TriangleAlert,
	Unplug,
} from "lucide-react";
import { MessageResponse } from "@/components/ai-elements/message";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { GroupPicker } from "@/components/ui/group-picker";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import { ImageFilePreview, ImageUpload } from "@/components/ui/image-upload";
import { SkillAvatar } from "@/components/ui/skill-avatar";
import {
	HeaderButton,
	HeaderPrimaryButton,
	HeaderReadOnly,
	SubpageHeader,
	UnsavedBadge,
} from "@/components/layout/subpage-header";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as skillsApi from "@/lib/api/resources/skills";
import { AGENT_COLORS } from "@/lib/colors";
import { groupOptions } from "@/lib/groups";
import { SkillDeleteDescription } from "./skill-delete-description";
import type { ResourceVisibility } from "@/types/visibility";
import { cn } from "@/lib/utils";
import { useSkillsStore } from "@/stores/skills-store";
import { useUnsavedChangesWarning } from "@/hooks/use-unsaved-changes-warning";
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

// A switch, like `toneClass` in the diff dialog, not a keyed object: the
// compiler checks every tone is covered so there is no missing-key case to
// fall back from, and a bracket lookup — even on a typed union — reads to
// static analysis as an object injection sink.
function noticeTone(tone: NoticeTone): { box: string; icon: string } {
	switch (tone) {
		case "warning":
			return {
				box: "border-[#F0DCC2] bg-[#FDF9F0] text-[#7A5C1E] dark:border-[#7A5C1E]/40 dark:bg-[#7A5C1E]/10 dark:text-[#E8C27A]",
				icon: "text-[#B98B2E] dark:text-[#E8C27A]",
			};
		case "alert":
			return {
				box: "border-destructive/20 bg-destructive/10 text-destructive",
				icon: "text-destructive",
			};
		case "plain":
			return {
				box: "border-input bg-petrol-tint text-body dark:border-white/10 dark:bg-white/[0.04] dark:text-panel-body",
				icon: "text-petrol",
			};
	}
}

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
	const style = noticeTone(tone);
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
	group: string;
	emoji: string | null;
	color: string | null;
	visibility: ResourceVisibility;
	teamIds: string[];
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
	const confirmDialog = useConfirmDialog();
	const { resolvedTheme } = useTheme();
	const createSkill = useSkillsStore((state) => state.createSkill);
	const updateSkill = useSkillsStore((state) => state.updateSkill);
	const setSkillImageRevision = useSkillsStore(
		(state) => state.setSkillImageRevision,
	);
	const librarySkills = useSkillsStore((state) => state.skills);
	const [reviewOpen, setReviewOpen] = useState(reviewOnOpen && Boolean(skill?.updateAvailable));
	// The repository's, whether or not it is still connected: the files and
	// scripts are in the row either way, so they are shown either way.
	const sourced = skill ? isSourced(skill) : false;
	const detached = skill ? isDetached(skill) : false;

	const initial = useMemo<Draft>(
		() =>
			skill
				? {
						content: skill.content,
						files: skill.files,
						group: skill.group ?? "",
						emoji: skill.emoji,
						color: skill.color,
						visibility: skill.visibility,
						teamIds: skill.teamIds,
					}
				: {
						content: NEW_SKILL,
						files: [],
						group: "",
						emoji: null,
						color: AGENT_COLORS[0],
						visibility: "workspace",
						teamIds: [],
					},
		[skill],
	);
	const [draft, setDraft] = useState<Draft>(initial);
	const [showIdentityPicker, setShowIdentityPicker] = useState(false);
	const [imageFile, setImageFile] = useState<File | null>(null);
	const [removeImage, setRemoveImage] = useState(false);
	const identityPickerRef = useRef<HTMLDivElement>(null);
	const currentImageUrl =
		skill?.id && skill.imageRevision
			? skillsApi.skillImageUrl(skill.id, skill.imageRevision)
			: null;
	const fields = useMemo(() => splitSkillMarkdown(draft.content), [draft.content]);
	// The form edits only a flat frontmatter; reading needs just the body.
	const body = useMemo(() => fields?.body ?? skillBody(draft.content), [fields, draft.content]);
	// A document whose frontmatter the form cannot round-trip (a folded
	// scalar, a flow collection) is shown, not edited: export it, edit the
	// file, import it again.
	const locked = fields === null;
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const isDirty =
		!readOnly &&
		(JSON.stringify(draft) !== JSON.stringify(initial) ||
			imageFile !== null ||
			removeImage);
	useUnsavedChangesWarning(isDirty);
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
		!bodyError &&
		(draft.visibility !== "teams" || draft.teamIds.length > 0);

	useEffect(() => {
		if (!showIdentityPicker) return;
		const close = (event: MouseEvent) => {
			if (!identityPickerRef.current?.contains(event.target as Node)) {
				setShowIdentityPicker(false);
			}
		};
		document.addEventListener("mousedown", close);
		return () => {
			document.removeEventListener("mousedown", close);
		};
	}, [showIdentityPicker]);

	const selectEmoji = (data: EmojiClickData) => {
		setDraft((current) => ({ ...current, emoji: data.emoji }));
		setShowIdentityPicker(false);
	};

	const handleSave = async () => {
		if (!canSave) return;
		setIsSaving(true);
		setError(null);
		try {
			let imageUploadFailed = false;
			let saved = skill
				? await updateSkill(skill.id, { ...draft, revision: skill.revision })
				: await createSkill(draft);
			if (imageFile) {
				try {
					const revision = await skillsApi.uploadSkillImage(
						saved.id,
						imageFile,
					);
					saved = { ...saved, imageRevision: revision };
					setSkillImageRevision(saved.id, revision);
				} catch (imageError) {
					if (skill) throw imageError;
					imageUploadFailed = true;
				}
			} else if (removeImage && saved.imageRevision) {
				await skillsApi.deleteSkillImage(saved.id);
				saved = { ...saved, imageRevision: null };
				setSkillImageRevision(saved.id, null);
			}
			if (imageUploadFailed) {
				toast.warning("Skill created, but its image could not be uploaded.");
			}
			onSaved(saved);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save the skill."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleCancel = async () => {
		if (
			isDirty &&
			!(await confirmDialog({
				title: "Discard unsaved changes?",
				description: "Your skill edits will be lost and cannot be recovered.",
				confirmLabel: "Discard changes",
				destructive: true,
			}))
		)
			return;
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
		"min-h-[300px] w-full flex-1 resize-none rounded-lg border border-input bg-sidebar p-4 text-[12.5px] leading-[1.7] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] [scrollbar-width:thin]";

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
				{readOnly && onEdit && (
					<HeaderPrimaryButton onClick={onEdit}>Edit</HeaderPrimaryButton>
				)}
				{readOnly && skill && sourced && (
					<HeaderReadOnly
						title={
							detached
								? `From a repository that is no longer connected${
										skill.sourcePath ? `, ${skill.sourcePath}` : ""
									}, connect it again to change this skill`
								: `Synced from ${skill.sourceName ?? "a repository"}${
										skill.sourcePath ? `, ${skill.sourcePath}` : ""
									}, edited in the repository, not here`
						}
					/>
				)}
				{!readOnly && (
					<>
						<HeaderButton
							disabled={isSaving}
							onClick={() => {
								void handleCancel();
							}}
						>
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
						<div
							ref={identityPickerRef}
							className={cn(
								"relative shrink-0",
								!(readOnly || sourced || locked) && "mt-[22px]",
							)}
						>
							<button
								type="button"
								disabled={readOnly || locked}
								aria-label={
									readOnly || locked
										? undefined
										: "Change skill identity"
								}
								onClick={() => {
									setShowIdentityPicker((current) => !current);
								}}
								className="relative flex size-12 cursor-pointer items-center justify-center rounded-xl transition-opacity hover:opacity-90 disabled:cursor-default disabled:hover:opacity-100"
							>
								{imageFile ? (
									<ImageFilePreview
										file={imageFile}
										className="rounded-xl"
									/>
								) : (
									<SkillAvatar
										skillId={skill?.id}
										name={name}
										emoji={draft.emoji}
										color={draft.color}
										imageRevision={
											removeImage ? null : skill?.imageRevision
										}
										size="md"
										className="pointer-events-none size-full"
									/>
								)}
								{!(readOnly || locked) && (
									<span className="absolute -bottom-[5px] -right-[5px] flex size-[18px] items-center justify-center rounded-full border border-input bg-card shadow-raised">
										<Pencil className="size-[9px] text-subtle dark:text-panel-body" />
									</span>
								)}
							</button>
							{showIdentityPicker && (
								<div className="absolute left-0 top-full z-50 mt-2">
									<div className="rounded-t-lg border border-b-0 border-border bg-card p-3">
										<ImageUpload
											currentUrl={currentImageUrl}
											file={imageFile}
											removed={removeImage}
											onFileChange={(file) => {
												setImageFile(file);
												if (file) setRemoveImage(false);
											}}
											onRemove={() => {
												setImageFile(null);
												setRemoveImage(Boolean(skill?.imageRevision));
											}}
											label="Skill image"
										/>
									</div>
									<EmojiPicker
										onEmojiClick={selectEmoji}
										theme={
											resolvedTheme === "dark"
												? Theme.DARK
												: Theme.LIGHT
										}
										skinTonesDisabled
										previewConfig={{ showPreview: false }}
									/>
									<div className="flex items-center justify-center gap-2 rounded-b-lg border-t border-border bg-card px-3 py-2">
										{AGENT_COLORS.map((candidate) => (
											<button
												key={candidate}
												type="button"
												aria-label={`Use color ${candidate}`}
												style={{ backgroundColor: candidate }}
												onClick={() => {
													setDraft((current) => ({
														...current,
														color: candidate,
													}));
												}}
												className={cn(
													"size-7 cursor-pointer rounded-full transition-transform hover:scale-110",
													draft.color === candidate &&
														"ring-2 ring-meta ring-offset-2 ring-offset-card",
												)}
											/>
										))}
										<label
											title="Custom color"
											className={cn(
												"relative size-7 cursor-pointer overflow-hidden rounded-full bg-[conic-gradient(#e84393,#e17055,#fdcb6e,#00b894,#0984e3,#6c5ce7,#e84393)] transition-transform hover:scale-110",
												draft.color !== null &&
													!AGENT_COLORS.includes(draft.color) &&
													"ring-2 ring-meta ring-offset-2 ring-offset-card",
											)}
										>
											<span className="absolute inset-[5px] rounded-full border border-white/80 bg-card" />
											<input
												type="color"
												value={draft.color ?? AGENT_COLORS[0]}
												aria-label="Custom skill color"
												onChange={(event) => {
													setDraft((current) => ({
														...current,
														color: event.target.value.toUpperCase(),
													}));
												}}
												className="absolute inset-0 size-full cursor-pointer opacity-0"
											/>
										</label>
									</div>
								</div>
							)}
						</div>
						{readOnly || sourced || locked ? (
							<div className="min-w-0 flex-1">
								<div className="flex min-w-0 flex-wrap items-center gap-2">
									<h1 className="min-w-0 truncate py-[2px] text-[19px] font-semibold tracking-[-0.01em] text-petrol">
										{name || "untitled"}
									</h1>
									{skill?.updateAvailable && (
										<span className="shrink-0 rounded-[4px] bg-warning-bg px-1.5 py-px text-[9px] font-semibold text-warning">
											Update
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
							<div className="flex min-w-0 flex-1 flex-col gap-4">
								<label>
									<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
										Name
									</span>
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
											"text-[15px] font-semibold tracking-[-0.01em] text-petrol dark:text-panel-terminal",
											nameError && fields.name && "border-destructive",
										)}
									/>
								</label>
								<label>
									<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
										Description
									</span>
									<textarea
										maxLength={1024}
										value={fields.description}
										onChange={(e) => {
											setFields({ description: e.target.value });
										}}
										placeholder="What the skill does and when to use it, this is how agents decide to pick it"
										rows={3}
										className={cn(
											fieldInputClass,
											"resize-y py-2.5 text-[13px] font-medium leading-5 text-body dark:text-panel-body",
										)}
									/>
								</label>
								{/* Rule violations only — an empty required field is what the
								    disabled Create button says, not a red line on a blank form. */}
								{(nameError && fields.name) || (descriptionError && fields.description) ? (
									<p className="-mt-2 text-[11.5px] text-destructive">
										{(fields.name && nameError) || descriptionError}
									</p>
								) : null}
							</div>
						)}
					</div>

					{!readOnly && (
						<div className="mt-4 flex flex-col gap-4">
							<GroupPicker
								value={draft.group}
								groups={groupOptions(librarySkills)}
								onChange={(group) => {
									setDraft((current) => ({ ...current, group }));
								}}
							/>
							<VisibilityPicker
								visibility={draft.visibility}
								teamIds={draft.teamIds}
								onChange={(visibility, teamIds) => {
									setDraft((current) => ({
										...current,
										visibility,
										teamIds,
									}));
								}}
							/>
						</div>
					)}
					{readOnly && skill && (
						<div className="mt-4">
							<VisibilityBadge
								visibility={skill.visibility}
								teamIds={skill.teamIds}
								showTeams
							/>
						</div>
					)}

					{error && (
						<EditorNotice tone="alert" icon={<CircleAlert />}>
							{error}
						</EditorNotice>
					)}

					{skill && detached && (
						<EditorNotice icon={<Unplug />}>
							{/* The URL, not the word "repository": reconnecting is matched on
							    it, so the one action this suggests needs it spelled out. */}
							<Link href="/skills?view=sources" className="font-semibold text-petrol hover:underline dark:text-panel-terminal">
								{repoLabel(skill.sourceUrl) || "Its repository"}
							</Link>{" "}
							is no longer connected. The skill keeps running, pinned to{" "}
							<span className="font-mono text-[11.5px]">{shortRevision(skill.sourceRevision)}</span>, connect{" "}
							{skill.sourceUrl ? (
								<span className="font-mono text-[11.5px]">{skill.sourceUrl}</span>
							) : (
								"the repository"
							)}{" "}
							again to
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
							as of the last sync, it keeps working, pinned to{" "}
							<span className="font-mono text-[11.5px]">{shortRevision(skill.sourceRevision)}</span>.
						</EditorNotice>
					)}

					{scriptCount > 0 && (
						<EditorNotice icon={<TerminalSquare />}>
							This skill requires an agent with code execution. Its {scriptCount}{" "}
							script{scriptCount === 1 ? "" : "s"} only run there, the instructions
							apply on any agent.
						</EditorNotice>
					)}

					<div className="mt-6 flex min-h-[24px] shrink-0 items-center justify-between border-b border-border pb-2">
						<span className="text-[10.5px] font-semibold text-label dark:text-muted-foreground">
							Instructions
						</span>
						{!readOnly && !locked && (
							<span className="text-[10.5px] text-meta dark:text-panel-dim">
								markdown, name, description and this text make the SKILL.md
							</span>
						)}
					</div>

					<div className="flex min-h-0 flex-1 flex-col pt-4">
						{readOnly || sourced || locked ? (
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
							A skill written here is one SKILL.md, it runs on any agent.
							<span className="mt-1 block text-[12px]">
								Scripts and reference files come from a{" "}
								<Link href="/skills?view=sources" className="font-semibold text-petrol hover:underline dark:text-panel-terminal">
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

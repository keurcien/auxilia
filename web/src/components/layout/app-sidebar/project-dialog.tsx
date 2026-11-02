"use client";

import { useEffect, useRef, useState } from "react";
import EmojiPicker, { type EmojiClickData, Theme } from "emoji-picker-react";
import { Folder, X } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";

import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useProjectsStore } from "@/stores/projects-store";
import type { Project } from "@/types/projects";
import type { ResourceVisibility } from "@/types/visibility";

export function ProjectDialog({
	open,
	onOpenChange,
	project,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	project: Project | null;
}) {
	const { resolvedTheme } = useTheme();
	const createProject = useProjectsStore((state) => state.createProject);
	const updateProject = useProjectsStore((state) => state.updateProject);
	const [name, setName] = useState("");
	const [emoji, setEmoji] = useState<string | null>(null);
	const [description, setDescription] = useState("");
	const [visibility, setVisibility] =
		useState<ResourceVisibility>("personal");
	const [teamIds, setTeamIds] = useState<string[]>([]);
	const [saving, setSaving] = useState(false);
	const [pickerOpen, setPickerOpen] = useState(false);
	const emojiTriggerRef = useRef<HTMLButtonElement>(null);

	useEffect(() => {
		if (!open) return;
		setName(project?.name ?? "");
		setEmoji(project?.emoji ?? null);
		setDescription(project?.description ?? "");
		setVisibility(project?.visibility ?? "personal");
		setTeamIds(project?.teamIds ?? []);
		setPickerOpen(false);
	}, [open, project]);

	const canSave =
		name.trim().length > 0 && (visibility !== "teams" || teamIds.length > 0);

	const save = async () => {
		if (!canSave || saving) return;
		setSaving(true);
		try {
			const payload = {
				name: name.trim(),
				emoji,
				description: description.trim(),
				visibility,
				teamIds,
			};
			if (project) {
				await updateProject(project.id, payload);
			} else {
				await createProject(payload);
			}
			onOpenChange(false);
		} catch (error) {
			toast.error(getApiErrorMessage(error, "The project could not be saved."));
		} finally {
			setSaving(false);
		}
	};

	const selectEmoji = (data: EmojiClickData) => {
		setEmoji(data.emoji);
		setPickerOpen(false);
		requestAnimationFrame(() => {
			emojiTriggerRef.current?.focus();
		});
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent
				onEscapeKeyDown={(event) => {
					if (!pickerOpen) return;
					event.preventDefault();
					setPickerOpen(false);
					requestAnimationFrame(() => {
						emojiTriggerRef.current?.focus();
					});
				}}
			>
				<DialogHeader>
					<DialogTitle>{project ? "Edit project" : "Create project"}</DialogTitle>
					<DialogDescription>
						Group conversations, triggers, and folders in one shared space.
					</DialogDescription>
				</DialogHeader>
				<div>
					<label
						htmlFor="project-name"
						className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground"
					>
						Name and icon
					</label>
					<div className="flex items-center gap-2">
						<div className="relative">
							<button
								ref={emojiTriggerRef}
								type="button"
								aria-label="Choose project emoji"
								aria-expanded={pickerOpen}
								onKeyDown={(event) => {
									if (
										event.key !== "ArrowDown" &&
										event.key !== "ArrowUp"
									) {
										return;
									}
									event.preventDefault();
									setPickerOpen(true);
								}}
								onClick={() => {
									setPickerOpen((value) => !value);
								}}
								className="flex size-10 cursor-pointer items-center justify-center rounded-[9px] border border-input bg-card text-lg outline-none transition-colors hover:border-border-hover focus-visible:ring-2 focus-visible:ring-ring/30"
							>
								{emoji ?? <Folder className="size-4 text-petrol" />}
							</button>
							{pickerOpen && (
								<div
									role="region"
									aria-label="Choose project emoji"
									className="absolute left-0 top-full z-[80] mt-2 shadow-xl"
								>
									<EmojiPicker
										autoFocusSearch
										onEmojiClick={selectEmoji}
										theme={
											resolvedTheme === "dark" ? Theme.DARK : Theme.LIGHT
										}
										skinTonesDisabled
										previewConfig={{ showPreview: false }}
									/>
								</div>
							)}
						</div>
						<input
							id="project-name"
							autoFocus
							maxLength={255}
							value={name}
							onChange={(event) => {
								setName(event.target.value);
							}}
							onKeyDown={(event) => {
								if (event.key === "Enter") {
									event.preventDefault();
									void save();
								}
							}}
							placeholder="Project name"
							className="h-10 min-w-0 flex-1 rounded-[9px] border border-input bg-card px-3 text-[13.5px] font-medium text-foreground outline-none focus:border-petrol"
						/>
						{emoji && (
							<button
								type="button"
								aria-label="Clear project emoji"
								title="Use folder icon"
								onClick={() => {
									setEmoji(null);
								}}
								className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta outline-none transition-colors hover:bg-hover hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/30 dark:hover:bg-white/10 dark:hover:text-white"
							>
								<X className="size-3.5" />
							</button>
						)}
					</div>
				</div>
				<label className="block">
					<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
						Description
					</span>
					<textarea
						maxLength={4_000}
						value={description}
						onChange={(event) => {
							setDescription(event.target.value);
						}}
						placeholder="Describe the project, its purpose, and its goals."
						className="min-h-24 w-full resize-y rounded-[9px] border border-input bg-card px-3 py-2.5 text-[13px] leading-5 text-foreground outline-none placeholder:text-meta focus:border-petrol"
					/>
				</label>
				<VisibilityPicker
					visibility={visibility}
					teamIds={teamIds}
					onChange={(nextVisibility, nextTeamIds) => {
						setVisibility(nextVisibility);
						setTeamIds(nextTeamIds);
					}}
				/>
				<DialogFooter>
					<DialogButton
						variant="outline"
						onClick={() => {
							onOpenChange(false);
						}}
					>
						Cancel
					</DialogButton>
					<DialogButton
						disabled={!canSave || saving}
						onClick={() => {
							void save();
						}}
					>
						{saving ? "Saving…" : project ? "Save changes" : "Create project"}
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

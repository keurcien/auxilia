"use client";

import { useState } from "react";
import EmojiPicker, { type EmojiClickData, Theme } from "emoji-picker-react";
import { AlertTriangle, Loader2, SmilePlus, Trash2, X } from "lucide-react";
import { useTheme } from "next-themes";

import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { ImageFilePreview, ImageUpload } from "@/components/ui/image-upload";
import { WorkspaceAvatar } from "@/components/ui/workspace-avatar";
import * as workspacesApi from "@/lib/api/resources/workspaces";
import { getApiErrorMessage } from "@/lib/api/errors";
import { AGENT_COLORS } from "@/lib/colors";
import { cn } from "@/lib/utils";
import { currentWorkspaceSwitchDestination } from "@/lib/workspace-navigation";
import { useWorkspacesStore } from "@/stores/workspaces-store";
import type { Workspace } from "@/types/workspaces";

interface EditWorkspaceDialogProps {
	workspace: Workspace | null;
	open: boolean;
	onOpenChange: (open: boolean) => void;
}

export function EditWorkspaceDialog({
	workspace,
	open,
	onOpenChange,
}: EditWorkspaceDialogProps) {
	const { resolvedTheme } = useTheme();
	const updateWorkspace = useWorkspacesStore((state) => state.updateWorkspace);
	const setWorkspaceImageRevision = useWorkspacesStore(
		(state) => state.setWorkspaceImageRevision,
	);
	const [name, setName] = useState(workspace?.name ?? "");
	const [emoji, setEmoji] = useState<string | null>(workspace?.emoji ?? null);
	const [color, setColor] = useState<string | null>(workspace?.color ?? null);
	const [imageFile, setImageFile] = useState<File | null>(null);
	const [removeImage, setRemoveImage] = useState(false);
	const [pickerOpen, setPickerOpen] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const [deleteOpen, setDeleteOpen] = useState(false);
	const [deleteConfirmation, setDeleteConfirmation] = useState("");
	const [deleteError, setDeleteError] = useState<string | null>(null);
	const [deleting, setDeleting] = useState(false);

	if (!workspace) return null;

	const currentImageUrl =
		workspace.imageRevision && !removeImage
			? workspacesApi.workspaceImageUrl(workspace.id, workspace.imageRevision)
			: null;

	const setOpen = (nextOpen: boolean) => {
		if (!nextOpen && (saving || deleting || deleteOpen)) return;
		onOpenChange(nextOpen);
	};

	const selectEmoji = (data: EmojiClickData) => {
		setEmoji(data.emoji);
		setPickerOpen(false);
	};

	const submit = async (event: React.FormEvent) => {
		event.preventDefault();
		const trimmed = name.trim();
		if (!trimmed) {
			setError("Enter a workspace name.");
			return;
		}

		setSaving(true);
		setError(null);
		try {
			await updateWorkspace(workspace.id, {
				name: trimmed,
				emoji,
				color,
			});
			if (imageFile) {
				const revision = await workspacesApi.uploadWorkspaceImage(
					workspace.id,
					imageFile,
				);
				setWorkspaceImageRevision(workspace.id, revision);
			} else if (removeImage && workspace.imageRevision) {
				await workspacesApi.deleteWorkspaceImage(workspace.id);
				setWorkspaceImageRevision(workspace.id, null);
			}
			onOpenChange(false);
		} catch (cause) {
			setError(getApiErrorMessage(cause, "Could not update the workspace."));
			setSaving(false);
		}
	};

	const deleteWorkspace = async () => {
		if (deleteConfirmation !== workspace.name) return;
		setDeleting(true);
		setDeleteError(null);
		const destination = currentWorkspaceSwitchDestination();
		try {
			await workspacesApi.deleteWorkspace(workspace.id, deleteConfirmation);
			setDeleteOpen(false);
			onOpenChange(false);
			window.location.assign(destination);
		} catch (cause) {
			setDeleteError(
				getApiErrorMessage(cause, "Could not delete the workspace."),
			);
			setDeleting(false);
		}
	};

	return (
		<>
			<Dialog open={open} onOpenChange={setOpen}>
				<DialogContent
					showCloseButton={!saving && !deleting && !deleteOpen}
					onEscapeKeyDown={(event) => {
						if (saving || deleting || deleteOpen) event.preventDefault();
					}}
					onPointerDownOutside={(event) => {
						if (saving || deleting || deleteOpen) event.preventDefault();
					}}
				>
					<form onSubmit={(event) => { void submit(event); }} className="contents">
					<DialogHeader>
						<DialogTitle>Edit workspace</DialogTitle>
						<DialogDescription>
							Update how this workspace appears to its members.
						</DialogDescription>
					</DialogHeader>

					<div className="flex items-center gap-4">
						<div className="size-16 overflow-hidden rounded-[14px]">
							{imageFile ? (
								<ImageFilePreview file={imageFile} className="rounded-[14px]" />
							) : (
								<WorkspaceAvatar
									workspaceId={workspace.id}
									name={name}
									emoji={emoji}
									color={color}
									imageRevision={removeImage ? null : workspace.imageRevision}
									size="lg"
								/>
							)}
						</div>
						<div className="min-w-0">
							<p className="truncate text-[14px] font-semibold text-foreground">
								{name.trim() || "Workspace"}
							</p>
							<p className="mt-1 text-[12px] text-meta dark:text-panel-dim">
								Preview
							</p>
						</div>
					</div>

					<div className="space-y-2">
						<label htmlFor="edit-workspace-name" className="text-[12px] font-semibold text-label dark:text-panel-dim">
							Name
						</label>
						<input
							id="edit-workspace-name"
							autoFocus
							maxLength={255}
							value={name}
							disabled={saving}
							onChange={(event) => { setName(event.target.value); }}
							className="h-10 w-full rounded-[8px] border border-input bg-card px-3 text-[13px] text-foreground outline-none transition-colors focus:border-border-hover focus:ring-2 focus:ring-ring/30 disabled:opacity-60 dark:border-white/10"
						/>
					</div>

					<div className="space-y-2">
						<span className="text-[12px] font-semibold text-label dark:text-panel-dim">
							Emoji and color
						</span>
						<div className="flex items-center gap-2">
							<div className="relative">
								<button
									type="button"
									disabled={saving}
									aria-label="Choose workspace emoji"
									aria-expanded={pickerOpen}
									onClick={() => { setPickerOpen((value) => !value); }}
									className="flex size-9 cursor-pointer items-center justify-center rounded-[8px] border border-input bg-card text-lg outline-none transition-colors hover:border-border-hover focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50"
								>
									{emoji || <SmilePlus className="size-4 text-meta" />}
								</button>
								{pickerOpen && (
									<div className="absolute left-0 top-full z-50 mt-2 shadow-xl">
										<EmojiPicker
											onEmojiClick={selectEmoji}
											theme={resolvedTheme === "dark" ? Theme.DARK : Theme.LIGHT}
											skinTonesDisabled
											previewConfig={{ showPreview: false }}
										/>
									</div>
								)}
							</div>
							{emoji && (
								<button
									type="button"
									disabled={saving}
									aria-label="Clear workspace emoji"
									title="Clear emoji"
									onClick={() => { setEmoji(null); }}
									className="flex size-8 cursor-pointer items-center justify-center rounded-[7px] text-meta outline-none hover:bg-hover focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50"
								>
									<X className="size-3.5" />
								</button>
							)}
							<div className="ml-1 flex flex-wrap gap-2" aria-label="Workspace color">
								{AGENT_COLORS.map((candidate) => (
									<button
										key={candidate}
										type="button"
										disabled={saving}
										aria-label={
											color === candidate
												? `Clear color ${candidate}`
												: `Use color ${candidate}`
										}
										aria-pressed={color === candidate}
										style={{ backgroundColor: candidate }}
										onClick={() => {
											setColor((current) =>
												current === candidate ? null : candidate,
											);
										}}
										className={cn(
											"size-7 cursor-pointer rounded-full outline-none transition-transform hover:scale-110 focus-visible:ring-2 focus-visible:ring-ring/50 disabled:opacity-50",
											color === candidate && "ring-2 ring-meta ring-offset-2 ring-offset-canvas",
										)}
									/>
								))}
								<label
									title="Custom color"
									className={cn(
										"relative size-7 cursor-pointer overflow-hidden rounded-full bg-[conic-gradient(#e84393,#e17055,#fdcb6e,#00b894,#0984e3,#6c5ce7,#e84393)] outline-none transition-transform hover:scale-110",
										color !== null &&
											!AGENT_COLORS.includes(color) &&
											"ring-2 ring-meta ring-offset-2 ring-offset-canvas",
										saving && "pointer-events-none opacity-50",
									)}
								>
									<span className="absolute inset-[5px] rounded-full border border-white/80 bg-card" />
									<input
										type="color"
										value={color ?? AGENT_COLORS[0]}
										disabled={saving}
										aria-label="Custom workspace color"
										onChange={(event) => {
											setColor(event.target.value.toUpperCase());
										}}
										className="absolute inset-0 size-full cursor-pointer opacity-0"
									/>
								</label>
							</div>
						</div>
					</div>

					<ImageUpload
						currentUrl={currentImageUrl}
						file={imageFile}
						removed={removeImage}
						disabled={saving}
						onFileChange={(file) => {
							setImageFile(file);
							if (file) setRemoveImage(false);
						}}
						onRemove={() => {
							setImageFile(null);
							setRemoveImage(Boolean(workspace.imageRevision));
						}}
						label="Workspace image"
					/>

					{error && <p role="alert" className="text-[12px] text-destructive">{error}</p>}

					<DialogFooter>
						<DialogButton
							variant="destructive"
							disabled={saving || deleting}
							className="mr-auto"
							onClick={() => {
								setDeleteConfirmation("");
								setDeleteError(null);
								setDeleteOpen(true);
							}}
						>
							<Trash2 className="size-3.5" />
							Delete workspace
						</DialogButton>
						<DialogButton variant="outline" disabled={saving} onClick={() => { setOpen(false); }}>
							Cancel
						</DialogButton>
						<DialogButton type="submit" disabled={saving || !name.trim()}>
							{saving && <Loader2 className="size-3.5 animate-spin" />}
							Save
						</DialogButton>
					</DialogFooter>
					</form>
				</DialogContent>
			</Dialog>

			<Dialog
				open={deleteOpen}
				onOpenChange={(nextOpen) => {
					if (!deleting) setDeleteOpen(nextOpen);
				}}
			>
				<DialogContent
					showCloseButton={!deleting}
					onEscapeKeyDown={(event) => {
						if (deleting) event.preventDefault();
					}}
					onPointerDownOutside={(event) => {
						if (deleting) event.preventDefault();
					}}
				>
					<DialogHeader>
						<div className="mb-1 flex size-10 items-center justify-center rounded-full bg-destructive/10 text-destructive">
							<AlertTriangle className="size-5" />
						</div>
						<DialogTitle>Delete workspace?</DialogTitle>
						<DialogDescription>
							This permanently deletes <strong>{workspace.name}</strong> and
							all of its agents, threads, runs, skills, MCP servers, users’
							memberships, and settings. This action cannot be undone.
						</DialogDescription>
					</DialogHeader>

					<div className="space-y-2">
						<label
							htmlFor="delete-workspace-confirmation"
							className="text-[12px] font-semibold text-label dark:text-panel-dim"
						>
							Type <span className="font-mono">{workspace.name}</span> to
							confirm
						</label>
						<input
							id="delete-workspace-confirmation"
							autoFocus
							autoComplete="off"
							value={deleteConfirmation}
							disabled={deleting}
							onChange={(event) => {
								setDeleteConfirmation(event.target.value);
							}}
							className="h-10 w-full rounded-[8px] border border-input bg-card px-3 text-[13px] text-foreground outline-none transition-colors focus:border-destructive focus:ring-2 focus:ring-destructive/20 disabled:opacity-60 dark:border-white/10"
						/>
					</div>

					{deleteError && (
						<p role="alert" className="text-[12px] text-destructive">
							{deleteError}
						</p>
					)}

					<DialogFooter>
						<DialogButton
							variant="outline"
							disabled={deleting}
							onClick={() => {
								setDeleteOpen(false);
							}}
						>
							Cancel
						</DialogButton>
						<DialogButton
							variant="destructive"
							disabled={deleting || deleteConfirmation !== workspace.name}
							onClick={() => {
								void deleteWorkspace();
							}}
						>
							{deleting && <Loader2 className="size-3.5 animate-spin" />}
							Delete workspace
						</DialogButton>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</>
	);
}

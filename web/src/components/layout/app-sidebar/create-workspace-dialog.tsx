"use client";

import { useState } from "react";
import EmojiPicker, { type EmojiClickData, Theme } from "emoji-picker-react";
import { Loader2, SmilePlus, X } from "lucide-react";
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

export function CreateWorkspaceDialog({
	open,
	onOpenChange,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
}) {
	const { resolvedTheme } = useTheme();
	const createWorkspace = useWorkspacesStore((state) => state.createWorkspace);
	const updateWorkspace = useWorkspacesStore((state) => state.updateWorkspace);
	const setWorkspaceImageRevision = useWorkspacesStore(
		(state) => state.setWorkspaceImageRevision,
	);
	const [name, setName] = useState("");
	const [emoji, setEmoji] = useState<string | null>(null);
	const [color, setColor] = useState<string | null>(null);
	const [imageFile, setImageFile] = useState<File | null>(null);
	const [pickerOpen, setPickerOpen] = useState(false);
	const [createdWorkspaceId, setCreatedWorkspaceId] = useState<string | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);

	const setOpen = (nextOpen: boolean) => {
		if (!nextOpen && submitting) return;
		if (!nextOpen) {
			setName("");
			setEmoji(null);
			setColor(null);
			setImageFile(null);
			setPickerOpen(false);
			setCreatedWorkspaceId(null);
			setError(null);
		}
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
		setSubmitting(true);
		setError(null);
		const destination = currentWorkspaceSwitchDestination();
		try {
			let workspaceId = createdWorkspaceId;
			if (workspaceId) {
				await updateWorkspace(workspaceId, { name: trimmed, emoji, color });
			} else {
				const workspace = await createWorkspace({
					name: trimmed,
					emoji,
					color,
				});
				workspaceId = workspace.id;
				setCreatedWorkspaceId(workspace.id);
			}
			if (imageFile) {
				const revision = await workspacesApi.uploadWorkspaceImage(
					workspaceId,
					imageFile,
				);
				setWorkspaceImageRevision(workspaceId, revision);
			}
			window.location.assign(destination);
		} catch (cause) {
			setError(getApiErrorMessage(cause, "Could not create the workspace."));
			setSubmitting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={setOpen}>
			<DialogContent
				showCloseButton={!submitting}
				onEscapeKeyDown={(event) => {
					if (submitting) event.preventDefault();
				}}
				onPointerDownOutside={(event) => {
					if (submitting) event.preventDefault();
				}}
			>
				<form onSubmit={(event) => { void submit(event); }} className="contents">
					<DialogHeader>
						<DialogTitle>Create workspace</DialogTitle>
						<DialogDescription>
							Create a separate space for agents, people, and integrations.
						</DialogDescription>
					</DialogHeader>
					<div className="flex items-center gap-4">
						<div className="size-16 overflow-hidden rounded-[14px]">
							{imageFile ? (
								<ImageFilePreview file={imageFile} className="rounded-[14px]" />
							) : (
								<WorkspaceAvatar
									name={name}
									emoji={emoji}
									color={color}
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
						<label htmlFor="workspace-name" className="text-[12px] font-semibold text-label dark:text-panel-dim">
							Name
						</label>
						<input
							id="workspace-name"
							autoFocus
							maxLength={255}
							value={name}
							onChange={(event) => { setName(event.target.value); }}
							placeholder="Acme"
							className="h-10 w-full rounded-[8px] border border-input bg-card px-3 text-[13px] text-foreground outline-none transition-colors placeholder:text-faint focus:border-border-hover focus:ring-2 focus:ring-ring/30 dark:border-white/10"
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
									disabled={submitting}
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
									disabled={submitting}
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
										disabled={submitting}
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
										submitting && "pointer-events-none opacity-50",
									)}
								>
									<span className="absolute inset-[5px] rounded-full border border-white/80 bg-card" />
									<input
										type="color"
										value={color ?? AGENT_COLORS[0]}
										disabled={submitting}
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
						file={imageFile}
						disabled={submitting}
						onFileChange={setImageFile}
						onRemove={() => { setImageFile(null); }}
						label="Workspace image"
					/>
					{error && <p role="alert" className="text-[12px] text-destructive">{error}</p>}
					<DialogFooter>
						<DialogButton variant="outline" disabled={submitting} onClick={() => { setOpen(false); }}>
							Cancel
						</DialogButton>
						<DialogButton type="submit" disabled={submitting || !name.trim()}>
							{submitting && <Loader2 className="size-3.5 animate-spin" />}
							Create
						</DialogButton>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

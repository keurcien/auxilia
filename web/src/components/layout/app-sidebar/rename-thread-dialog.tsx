"use client";

import { useEffect, useState } from "react";
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
import { getApiErrorMessage } from "@/lib/api/errors";
import * as threadsApi from "@/lib/api/resources/threads";
import { useProjectsStore } from "@/stores/projects-store";
import { useThreadsStore } from "@/stores/threads-store";

export interface RenameThreadTarget {
	id: string;
	title: string | null;
}

interface RenameThreadDialogProps {
	thread: RenameThreadTarget | null;
	onOpenChange: (open: boolean) => void;
	onRenamed?: (title: string) => void;
}

export function RenameThreadDialog({
	thread,
	onOpenChange,
	onRenamed,
}: RenameThreadDialogProps) {
	const renameThread = useThreadsStore((state) => state.renameThread);
	const refreshTree = useProjectsStore((state) => state.refreshTree);
	const [title, setTitle] = useState("");
	const [isSubmitting, setIsSubmitting] = useState(false);

	useEffect(() => {
		setTitle(thread?.title ?? "");
	}, [thread]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!thread || isSubmitting) return;
		const trimmed = title.trim();
		if (!trimmed || trimmed === thread.title?.trim()) {
			onOpenChange(false);
			return;
		}
		setIsSubmitting(true);
		try {
			await threadsApi.renameThread(thread.id, trimmed);
			renameThread(thread.id, trimmed);
			onRenamed?.(trimmed);
			onOpenChange(false);
			void refreshTree().catch(() => {});
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation could not be renamed."),
			);
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<Dialog open={thread !== null} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader>
					<DialogTitle>Rename conversation</DialogTitle>
					<DialogDescription>
						Give this conversation a new title
					</DialogDescription>
				</DialogHeader>

				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
					className="flex flex-col gap-5"
				>
					<div className="flex flex-col gap-[7px]">
						<label
							htmlFor="thread-title"
							className="text-[13px] font-semibold text-ink dark:text-panel-button"
						>
							Title
						</label>
						<input
							id="thread-title"
							type="text"
							autoFocus
							maxLength={255}
							placeholder="Conversation title"
							value={title}
							onChange={(e) => {
								setTitle(e.target.value);
							}}
							className="w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
						/>
					</div>

					<DialogFooter>
						<DialogButton
							variant="outline"
							onClick={() => {
								onOpenChange(false);
							}}
						>
							Cancel
						</DialogButton>
						<DialogButton type="submit" disabled={isSubmitting || !title.trim()}>
							{isSubmitting ? "Saving…" : "Save"}
						</DialogButton>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

"use client";

import { useEffect, useState } from "react";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api/client";
import { useThreadsStore } from "@/stores/threads-store";
import { Thread } from "@/types/threads";

interface RenameThreadDialogProps {
	thread: Thread | null;
	onOpenChange: (open: boolean) => void;
}

export function RenameThreadDialog({
	thread,
	onOpenChange,
}: RenameThreadDialogProps) {
	const { renameThread } = useThreadsStore();
	const [title, setTitle] = useState("");
	const [isSubmitting, setIsSubmitting] = useState(false);

	useEffect(() => {
		setTitle(thread?.firstMessageContent ?? "");
	}, [thread]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!thread) return;
		const trimmed = title.trim();
		if (!trimmed || trimmed === thread.firstMessageContent) {
			onOpenChange(false);
			return;
		}
		setIsSubmitting(true);
		try {
			await api.patch(`/threads/${thread.id}`, {
				firstMessageContent: trimmed,
			});
			renameThread(thread.id, trimmed);
			onOpenChange(false);
		} catch (error) {
			console.error("Error renaming thread: ", error);
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<Dialog open={thread !== null} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader>
					<DialogTitle>Rename thread</DialogTitle>
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
							placeholder="Thread title"
							value={title}
							onChange={(e) => {
								setTitle(e.target.value);
							}}
							className="w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
						/>
					</div>

					<DialogFooter>
						<button
							type="button"
							onClick={() => {
								onOpenChange(false);
							}}
							className="cursor-pointer rounded-[7px] border border-input px-[18px] py-2 text-[13px] font-semibold text-ink transition-colors hover:border-border-hover dark:text-panel-button dark:hover:border-white/30"
						>
							Cancel
						</button>
						<button
							type="submit"
							disabled={isSubmitting}
							className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
						>
							{isSubmitting ? "Saving…" : "Save"}
						</button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

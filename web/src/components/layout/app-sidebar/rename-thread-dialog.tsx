"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { SageInput } from "@/components/ui/sage-input";
import { SageButton } from "@/components/ui/sage-button";
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
			<DialogContent
				className="sm:max-w-[460px] rounded-[28px] p-0 gap-0 overflow-hidden"
				showCloseButton={false}
			>
				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
				>
					{/* Header */}
					<div className="flex items-start justify-between px-8 pt-7 pb-0">
						<div>
							<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[22px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
								Rename thread
							</DialogTitle>
							<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-1">
								Give this conversation a new title
							</p>
						</div>
						<button
							type="button"
							onClick={() => {
								onOpenChange(false);
							}}
							className="shrink-0 flex items-center justify-center w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 text-[#6B7F76] hover:bg-[#EDF4F0] dark:hover:bg-white/15 transition-colors cursor-pointer"
						>
							<X className="w-4 h-4" />
						</button>
					</div>

					{/* Content */}
					<div className="px-8 pt-6 pb-2">
						<label
							htmlFor="thread-title"
							className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
						>
							Title
						</label>
						<SageInput
							id="thread-title"
							autoFocus
							placeholder="Thread title"
							value={title}
							onChange={(e) => {
								setTitle(e.target.value);
							}}
						/>
					</div>

					{/* Footer */}
					<div className="flex items-center justify-end gap-2.5 px-8 pt-5 pb-6 mt-4 border-t border-[#F0F3F2] dark:border-white/5">
						<SageButton
							type="button"
							color="outline"
							onClick={() => {
								onOpenChange(false);
							}}
						>
							Cancel
						</SageButton>
						<SageButton type="submit" disabled={isSubmitting}>
							{isSubmitting ? "Saving..." : "Save"}
						</SageButton>
					</div>
				</form>
			</DialogContent>
		</Dialog>
	);
}

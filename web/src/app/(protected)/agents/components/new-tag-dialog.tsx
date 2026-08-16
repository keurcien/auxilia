"use client";

import { useEffect, useState } from "react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { AgentTag } from "@/types/agents";

interface NewTagDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	tag?: AgentTag | null;
	onTagCreated?: (tag: AgentTag) => void;
	onTagUpdated?: (tag: AgentTag) => void;
}

export default function NewTagDialog({
	open,
	onOpenChange,
	tag,
	onTagCreated,
	onTagUpdated,
}: NewTagDialogProps) {
	const isEdit = !!tag;
	const [name, setName] = useState("");
	const [isSubmitting, setIsSubmitting] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (open) {
			setName(tag?.name ?? "");
			setError(null);
			setIsSubmitting(false);
		}
	}, [open, tag]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		const trimmed = name.trim();
		if (!trimmed) return;
		setError(null);
		setIsSubmitting(true);
		try {
			if (tag) {
				const response = await api.patch(`/tags/${tag.id}`, { name: trimmed });
				onTagUpdated?.(response.data as AgentTag);
			} else {
				const response = await api.post("/tags/", { name: trimmed });
				onTagCreated?.(response.data as AgentTag);
			}
			onOpenChange(false);
		} catch (err: unknown) {
			setError(getApiErrorMessage(err, "An error occurred"));
		} finally {
			setIsSubmitting(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[560px]">
				<DialogHeader>
					<DialogTitle>{isEdit ? "Edit tag" : "New tag"}</DialogTitle>
					<DialogDescription>
						Group agents under a section in the gallery
					</DialogDescription>
				</DialogHeader>

				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
					className="flex flex-col gap-5"
				>
					{error && (
						<div className="rounded-[10px] bg-[#FBEFED] px-3.5 py-2.5 text-[13px] font-medium text-[#B04A3A] dark:bg-[#B04A3A]/10">
							{error}
						</div>
					)}

					<div className="flex flex-col gap-[7px]">
						<label
							htmlFor="tag-name"
							className="text-[13px] font-semibold text-ink dark:text-panel-button"
						>
							Name
						</label>
						<input
							id="tag-name"
							type="text"
							autoFocus
							placeholder="e.g. Productivity"
							value={name}
							onChange={(e) => {
								setName(e.target.value);
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
						<DialogButton type="submit" disabled={isSubmitting || !name.trim()}>
							{isSubmitting ? "Saving…" : isEdit ? "Save" : "Create tag"}
						</DialogButton>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}

"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { SageInput } from "@/components/ui/sage-input";
import { SageButton } from "@/components/ui/sage-button";
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
								{isEdit ? "Edit tag" : "New tag"}
							</DialogTitle>
							<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-2 leading-relaxed">
								Group agents under a section in the gallery
							</p>
						</div>
						<button
							type="button"
							aria-label="Close"
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
						{error && (
							<div className="mb-5 p-3.5 rounded-2xl bg-red-50 dark:bg-red-950/30 text-[13px] font-medium text-red-600 dark:text-red-400 font-[family-name:var(--font-dm-sans)]">
								{error}
							</div>
						)}

						<label
							htmlFor="tag-name"
							className="block font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#1E2D28] dark:text-foreground mb-2"
						>
							Name
						</label>
						<SageInput
							id="tag-name"
							autoFocus
							placeholder="e.g. Productivity"
							value={name}
							onChange={(e) => {
								setName(e.target.value);
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
						<SageButton type="submit" disabled={isSubmitting || !name.trim()}>
							{isSubmitting ? "Saving..." : isEdit ? "Save" : "Create tag"}
						</SageButton>
					</div>
				</form>
			</DialogContent>
		</Dialog>
	);
}

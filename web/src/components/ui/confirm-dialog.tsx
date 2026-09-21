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

interface ConfirmDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	title: string;
	description: React.ReactNode;
	/** The confirming button's label, e.g. "Delete skill". */
	confirmLabel: string;
	/** Red fill for irreversible actions (design 19a: never a bare red text button). */
	destructive?: boolean;
	/** Resolves when done; a rejection keeps the dialog open with the error. */
	onConfirm: () => Promise<void> | void;
	errorMessage?: string;
}

/**
 * Petrol Mono confirmation dialog — replaces `window.confirm` for actions
 * that need a sentence of context: title 16/700, description under it,
 * right-aligned outline Cancel + primary/destructive confirm.
 */
export default function ConfirmDialog({
	open,
	onOpenChange,
	title,
	description,
	confirmLabel,
	destructive = false,
	onConfirm,
	errorMessage = "Something went wrong. Please try again.",
}: ConfirmDialogProps) {
	const [isBusy, setIsBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		if (open) {
			setError(null);
			setIsBusy(false);
		}
	}, [open]);

	const handleConfirm = async () => {
		setIsBusy(true);
		setError(null);
		try {
			await onConfirm();
			onOpenChange(false);
		} catch {
			setError(errorMessage);
		} finally {
			setIsBusy(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[480px]">
				<DialogHeader>
					<DialogTitle>{title}</DialogTitle>
					<DialogDescription>{description}</DialogDescription>
				</DialogHeader>
				{error && (
					<div className="rounded-[10px] bg-[#FBEFED] px-3.5 py-2.5 text-[13px] font-medium text-[#B04A3A] dark:bg-[#B04A3A]/10">
						{error}
					</div>
				)}
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
						variant={destructive ? "destructive" : "primary"}
						disabled={isBusy}
						onClick={() => {
							void handleConfirm();
						}}
					>
						{isBusy ? "Working…" : confirmLabel}
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

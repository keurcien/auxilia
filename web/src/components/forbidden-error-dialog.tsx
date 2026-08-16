"use client";

import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";

interface ForbiddenErrorDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	title: string;
	message: string;
}

export default function ForbiddenErrorDialog({
	open,
	onOpenChange,
	title,
	message,
}: ForbiddenErrorDialogProps) {
	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{title}</DialogTitle>
					<DialogDescription>{message}</DialogDescription>
				</DialogHeader>
				<DialogFooter>
					<button
						type="button"
						onClick={() => {
							onOpenChange(false);
						}}
						className="cursor-pointer rounded-[7px] border border-input px-[18px] py-2 text-[13px] font-semibold text-ink transition-colors hover:border-border-hover dark:text-panel-button dark:hover:border-white/30"
					>
						Close
					</button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

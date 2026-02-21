"use client";

import { ShieldAlert } from "lucide-react";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

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
			<DialogContent
				className="sm:max-w-[560px] rounded-3xl p-0 gap-0"
				showCloseButton={false}
			>
				<DialogHeader className="p-6">
					<div className="flex items-center gap-3 mb-2">
						<ShieldAlert className="h-5 w-5 text-destructive" />
						<DialogTitle>{title}</DialogTitle>
					</div>
					<DialogDescription>{message}</DialogDescription>
				</DialogHeader>
				<DialogFooter className="p-6 pt-0">
					<Button
						variant="outline"
						onClick={() => onOpenChange(false)}
						className="cursor-pointer"
					>
						Close
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

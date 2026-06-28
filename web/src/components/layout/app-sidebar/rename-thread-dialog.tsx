"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
	Dialog,
	DialogContent,
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
	const [isLoading, setIsLoading] = useState(false);

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
		setIsLoading(true);
		try {
			await api.patch(`/threads/${thread.id}`, {
				firstMessageContent: trimmed,
			});
			renameThread(thread.id, trimmed);
			onOpenChange(false);
		} catch (error) {
			console.error("Error renaming thread: ", error);
		} finally {
			setIsLoading(false);
		}
	};

	return (
		<Dialog open={thread !== null} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-md">
				<DialogHeader>
					<DialogTitle>Rename thread</DialogTitle>
				</DialogHeader>

				<form
					onSubmit={(e) => {
						void handleSubmit(e);
					}}
					className="space-y-4"
				>
					<div className="space-y-2">
						<Label htmlFor="thread-title">Title</Label>
						<Input
							id="thread-title"
							type="text"
							autoFocus
							value={title}
							onChange={(e) => {
								setTitle(e.target.value);
							}}
							required
						/>
					</div>

					<Button
						type="submit"
						className="w-full cursor-pointer"
						disabled={isLoading}
					>
						{isLoading ? "Saving..." : "Save"}
					</Button>
				</form>
			</DialogContent>
		</Dialog>
	);
}

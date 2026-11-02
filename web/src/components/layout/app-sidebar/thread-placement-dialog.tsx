"use client";

import { useEffect, useMemo, useState } from "react";
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
import { getProjectFolderPath } from "@/lib/project-folders";
import { useProjectsStore } from "@/stores/projects-store";
import { useThreadsStore } from "@/stores/threads-store";

export interface ThreadPlacementTarget {
	id: string;
	title: string;
	projectId: string | null;
	folderId: string | null;
}

export function ThreadPlacementDialog({
	open,
	onOpenChange,
	thread,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	thread: ThreadPlacementTarget | null;
}) {
	const projects = useProjectsStore((state) => state.tree);
	const refreshTree = useProjectsStore((state) => state.refreshTree);
	const setThreadPlacement = useThreadsStore((state) => state.setThreadPlacement);
	const [projectId, setProjectId] = useState<string | null>(null);
	const [folderId, setFolderId] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);

	useEffect(() => {
		if (!open) return;
		setProjectId(thread?.projectId ?? null);
		setFolderId(thread?.folderId ?? null);
	}, [open, thread]);

	const folders = useMemo(
		() => projects.find((project) => project.id === projectId)?.folders ?? [],
		[projectId, projects],
	);

	const save = async () => {
		if (!thread || saving) return;
		setSaving(true);
		try {
			await setThreadPlacement(thread.id, projectId, folderId);
			await refreshTree();
			onOpenChange(false);
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation could not be moved."),
			);
		} finally {
			setSaving(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>Move conversation</DialogTitle>
					<DialogDescription className="truncate">
						Choose a project and folder for {thread?.title ?? "this conversation"}.
					</DialogDescription>
				</DialogHeader>
				<div className="grid gap-3 sm:grid-cols-2">
					<label className="block">
						<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
							Project
						</span>
						<select
							value={projectId ?? ""}
							onChange={(event) => {
								setProjectId(event.target.value || null);
								setFolderId(null);
							}}
							className="h-10 w-full cursor-pointer rounded-[9px] border border-input bg-card px-3 text-[13px] text-foreground outline-none focus:border-petrol"
						>
							<option value="">No project</option>
							{projects.map((project) => (
								<option key={project.id} value={project.id}>
									{project.emoji ? `${project.emoji} ` : ""}
									{project.name}
								</option>
							))}
						</select>
					</label>
					<label className="block">
						<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
							Folder
						</span>
						<select
							value={folderId ?? ""}
							disabled={projectId === null}
							onChange={(event) => {
								setFolderId(event.target.value || null);
							}}
							className="h-10 w-full cursor-pointer rounded-[9px] border border-input bg-card px-3 text-[13px] text-foreground outline-none focus:border-petrol disabled:cursor-not-allowed disabled:opacity-50"
						>
							<option value="">Project root</option>
							{folders.map((folder) => (
								<option key={folder.id} value={folder.id}>
									{getProjectFolderPath(folder, folders)}
								</option>
							))}
						</select>
					</label>
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
					<DialogButton
						disabled={!thread || saving}
						onClick={() => {
							void save();
						}}
					>
						{saving ? "Moving…" : "Move"}
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

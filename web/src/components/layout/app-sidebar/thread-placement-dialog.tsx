"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import {
	AsyncSearchSelect,
	type AsyncSearchOption,
} from "@/components/ui/async-search-select";
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
import * as projectsApi from "@/lib/api/resources/projects";
import { getProjectFolderPath } from "@/lib/project-folders";
import { useProjectsStore } from "@/stores/projects-store";
import { useThreadsStore } from "@/stores/threads-store";

export interface ThreadPlacementTarget {
	id: string;
	title: string;
	projectId: string | null;
	folderId: string | null;
}

/** Moves one conversation (`thread`) or several at once (`threads`). */
export function ThreadPlacementDialog({
	open,
	onOpenChange,
	thread,
	threads,
	onMoved,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	thread?: ThreadPlacementTarget | null;
	/** Keep the array stable while open: a new one resets the picked placement. */
	threads?: ThreadPlacementTarget[];
	onMoved?: () => void;
}) {
	const projects = useProjectsStore((state) => state.tree);
	const refreshTree = useProjectsStore((state) => state.refreshTree);
	const setThreadPlacement = useThreadsStore((state) => state.setThreadPlacement);
	const [projectId, setProjectId] = useState<string | null>(null);
	const [folderId, setFolderId] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const targets = useMemo(
		() => threads ?? (thread ? [thread] : []),
		[thread, threads],
	);

	useEffect(() => {
		if (!open) return;
		// Preselect the current placement only when every target shares it.
		const [first] = targets;
		const shared =
			first !== undefined &&
			targets.every(
				(target) =>
					target.projectId === first.projectId &&
					target.folderId === first.folderId,
			);
		setProjectId(shared ? first.projectId : null);
		setFolderId(shared ? first.folderId : null);
	}, [open, targets]);

	const selectedProject = projects.find((project) => project.id === projectId);
	const folders = selectedProject?.folders ?? [];
	const selectedFolder = folders.find((folder) => folder.id === folderId);
	const selectedProjectOption: AsyncSearchOption | null = selectedProject
		? {
				value: selectedProject.id,
				label: selectedProject.emoji
					? `${selectedProject.emoji} ${selectedProject.name}`
					: selectedProject.name,
				description: selectedProject.description || undefined,
			}
		: null;
	const selectedFolderOption: AsyncSearchOption | null = selectedFolder
		? {
				value: selectedFolder.id,
				label: getProjectFolderPath(selectedFolder, folders),
			}
		: null;
	const loadProjectOptions = useCallback(
		async (query: string, signal: AbortSignal) =>
			(await projectsApi.searchProjects(query, signal)).map((project) => ({
				value: project.id,
				label: project.emoji
					? `${project.emoji} ${project.name}`
					: project.name,
				description: project.description || undefined,
			})),
		[],
	);
	const loadFolderOptions = useCallback(
		async (query: string, signal: AbortSignal) => {
			if (!projectId) return [];
			return (
				await projectsApi.searchProjectFolders(projectId, query, signal)
			).map((folder) => ({
				value: folder.id,
				label: folder.path,
			}));
		},
		[projectId],
	);

	const save = async () => {
		if (targets.length === 0 || saving) return;
		setSaving(true);
		try {
			const results = await Promise.allSettled(
				targets.map((target) =>
					setThreadPlacement(target.id, projectId, folderId),
				),
			);
			const failures = results.filter(
				(result): result is PromiseRejectedResult =>
					result.status === "rejected",
			);
			await refreshTree();
			if (failures.length < targets.length) onMoved?.();
			if (failures.length === 0) {
				onOpenChange(false);
			} else if (targets.length === 1) {
				toast.error(
					getApiErrorMessage(
						failures[0]?.reason,
						"The conversation could not be moved.",
					),
				);
			} else {
				toast.error(
					`${failures.length} of ${targets.length} conversations could not be moved.`,
				);
			}
		} finally {
			setSaving(false);
		}
	};

	const bulk = targets.length > 1;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>
						{bulk ? `Move ${targets.length} conversations` : "Move conversation"}
					</DialogTitle>
					<DialogDescription className="truncate">
						{bulk
							? "Choose a project and folder for the selected conversations."
							: `Choose a project and folder for ${targets[0]?.title ?? "this conversation"}.`}
					</DialogDescription>
				</DialogHeader>
				<div className="grid gap-3 sm:grid-cols-2">
					<AsyncSearchSelect
						label="Project"
						value={projectId}
						selectedOption={selectedProjectOption}
						placeholder="Search projects"
						emptyValueLabel="No project"
						loadOptions={loadProjectOptions}
						onChange={(nextProjectId) => {
							setProjectId(nextProjectId);
							setFolderId(null);
						}}
					/>
					<AsyncSearchSelect
						label="Folder"
						value={folderId}
						selectedOption={selectedFolderOption}
						placeholder="Search folders"
						emptyValueLabel="Project root"
						disabled={projectId === null}
						loadOptions={loadFolderOptions}
						onChange={(nextFolderId) => {
							setFolderId(nextFolderId);
						}}
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
					<DialogButton
						disabled={targets.length === 0 || saving}
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

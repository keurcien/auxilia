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
import type { ProjectFolder, ProjectTree } from "@/types/projects";

const descendantIds = (
	folderId: string,
	folders: ProjectFolder[],
): Set<string> => {
	const result = new Set<string>([folderId]);
	let changed = true;
	while (changed) {
		changed = false;
		for (const folder of folders) {
			if (folder.parentId && result.has(folder.parentId) && !result.has(folder.id)) {
				result.add(folder.id);
				changed = true;
			}
		}
	}
	return result;
};

export function FolderDialog({
	open,
	onOpenChange,
	project,
	folder,
	initialParentId,
}: {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	project: ProjectTree | null;
	folder: ProjectFolder | null;
	initialParentId: string | null;
}) {
	const createFolder = useProjectsStore((state) => state.createFolder);
	const updateFolder = useProjectsStore((state) => state.updateFolder);
	const [name, setName] = useState("");
	const [parentId, setParentId] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);

	useEffect(() => {
		if (!open) return;
		setName(folder?.name ?? "");
		setParentId(folder?.parentId ?? initialParentId);
	}, [folder, initialParentId, open]);

	const unavailable = useMemo(
		() => (folder && project ? descendantIds(folder.id, project.folders) : new Set()),
		[folder, project],
	);

	const save = async () => {
		if (!project || !name.trim() || saving) return;
		setSaving(true);
		try {
			if (folder) {
				await updateFolder(folder.id, { name: name.trim(), parentId });
			} else {
				await createFolder(project.id, { name: name.trim(), parentId });
			}
			onOpenChange(false);
		} catch (error) {
			toast.error(getApiErrorMessage(error, "The folder could not be saved."));
		} finally {
			setSaving(false);
		}
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent>
				<DialogHeader>
					<DialogTitle>{folder ? "Edit folder" : "Create folder"}</DialogTitle>
					<DialogDescription>
						Choose a name and where this folder belongs.
					</DialogDescription>
				</DialogHeader>
				<label className="block">
					<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
						Name
					</span>
					<input
						autoFocus
						maxLength={255}
						value={name}
						onChange={(event) => {
							setName(event.target.value);
						}}
						className="h-10 w-full rounded-[9px] border border-input bg-card px-3 text-[13.5px] font-medium text-foreground outline-none focus:border-petrol"
					/>
				</label>
				<label className="block">
					<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
						Parent folder
					</span>
					<select
						value={parentId ?? ""}
						onChange={(event) => {
							setParentId(event.target.value || null);
						}}
						className="h-10 w-full cursor-pointer rounded-[9px] border border-input bg-card px-3 text-[13px] text-foreground outline-none focus:border-petrol"
					>
						<option value="">Project root</option>
						{project?.folders
							.filter((candidate) => !unavailable.has(candidate.id))
							.map((candidate) => (
								<option key={candidate.id} value={candidate.id}>
									{getProjectFolderPath(candidate, project?.folders ?? [])}
								</option>
							))}
					</select>
				</label>
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
						disabled={!name.trim() || saving}
						onClick={() => {
							void save();
						}}
					>
						{saving ? "Saving…" : folder ? "Save changes" : "Create folder"}
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

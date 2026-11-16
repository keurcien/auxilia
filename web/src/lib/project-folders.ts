import type {
	ProjectFolder,
	ProjectThread,
	ProjectTree,
	ProjectTrigger,
} from "@/types/projects";

export const PROJECT_ROOT = "__project_root__";

const parentKey = (folderId: string | null) => folderId ?? PROJECT_ROOT;

export interface NormalizedProjectTree {
	foldersById: Map<string, ProjectFolder>;
	foldersByParent: Map<string, ProjectFolder[]>;
	threadsByFolder: Map<string, ProjectThread[]>;
	triggersByFolder: Map<string, ProjectTrigger[]>;
}

function appendToMap<T>(map: Map<string, T[]>, key: string, item: T): void {
	const existing = map.get(key);
	if (existing) existing.push(item);
	else map.set(key, [item]);
}

export function normalizeProjectTree(
	project: Pick<ProjectTree, "folders" | "threads" | "triggers">,
): NormalizedProjectTree {
	const foldersById = new Map(
		project.folders.map((folder) => [folder.id, folder]),
	);
	const foldersByParent = new Map<string, ProjectFolder[]>();
	const threadsByFolder = new Map<string, ProjectThread[]>();
	const triggersByFolder = new Map<string, ProjectTrigger[]>();

	for (const folder of project.folders) {
		appendToMap(foldersByParent, parentKey(folder.parentId), folder);
	}
	for (const thread of project.threads) {
		appendToMap(threadsByFolder, parentKey(thread.folderId), thread);
	}
	for (const trigger of project.triggers) {
		appendToMap(triggersByFolder, parentKey(trigger.folderId), trigger);
	}
	for (const values of [
		...foldersByParent.values(),
		...threadsByFolder.values(),
		...triggersByFolder.values(),
	]) {
		values.sort((left, right) => {
			const leftName = "name" in left ? left.name : (left.title ?? "");
			const rightName = "name" in right ? right.name : (right.title ?? "");
			return leftName.localeCompare(rightName);
		});
	}

	return {
		foldersById,
		foldersByParent,
		threadsByFolder,
		triggersByFolder,
	};
}

export function getProjectFolderAncestors(
	folderId: string | null,
	foldersById: Map<string, ProjectFolder>,
): ProjectFolder[] {
	const result: ProjectFolder[] = [];
	const seen = new Set<string>();
	let currentId = folderId;
	while (currentId && !seen.has(currentId)) {
		seen.add(currentId);
		const folder = foldersById.get(currentId);
		if (!folder) break;
		result.unshift(folder);
		currentId = folder.parentId;
	}
	return result;
}

export interface ProjectFolderContentCount {
	folders: number;
	threads: number;
	triggers: number;
}

/** Everything under a folder, recursively; the folder itself is not counted. */
export function countProjectFolderContent(
	folderId: string,
	tree: NormalizedProjectTree,
): ProjectFolderContentCount {
	const count: ProjectFolderContentCount = {
		folders: 0,
		threads: 0,
		triggers: 0,
	};
	const seen = new Set<string>();
	const pending = [folderId];
	while (pending.length > 0) {
		const currentId = pending.pop();
		if (currentId === undefined || seen.has(currentId)) continue;
		seen.add(currentId);
		count.threads += tree.threadsByFolder.get(currentId)?.length ?? 0;
		count.triggers += tree.triggersByFolder.get(currentId)?.length ?? 0;
		for (const child of tree.foldersByParent.get(currentId) ?? []) {
			count.folders += 1;
			pending.push(child.id);
		}
	}
	return count;
}

export function getProjectFolderPath(
	folder: ProjectFolder,
	folders: ProjectFolder[],
): string {
	const byId = new Map(folders.map((candidate) => [candidate.id, candidate]));
	return getProjectFolderAncestors(folder.id, byId)
		.map((candidate) => candidate.name)
		.join(" / ");
}

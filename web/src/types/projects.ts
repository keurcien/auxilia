import type { ThreadSource } from "@/types/threads";
import type { TriggerType } from "@/types/triggers";
import type { ResourceVisibility } from "@/types/visibility";

export interface Project {
	id: string;
	workspaceId: string;
	ownerId: string;
	name: string;
	description: string;
	visibility: ResourceVisibility;
	teamIds: string[];
	canManage: boolean;
	createdAt: string;
	updatedAt: string;
}

export interface ProjectFolder {
	id: string;
	projectId: string;
	parentId: string | null;
	name: string;
	createdAt: string;
	updatedAt: string;
}

export interface ProjectFolderSearchResult {
	id: string;
	name: string;
	path: string;
}

export interface ProjectThread {
	id: string;
	agentId: string;
	title: string | null;
	source: ThreadSource;
	completedAt: string | null;
	folderId: string | null;
	canManage: boolean;
	createdAt: string;
}

export interface ProjectTrigger {
	id: string;
	name: string;
	triggerType: TriggerType;
	folderId: string | null;
	isActive: boolean;
	canManage: boolean;
}

export interface ProjectTree extends Project {
	folders: ProjectFolder[];
	threads: ProjectThread[];
	triggers: ProjectTrigger[];
}

export interface ProjectContextFileSummary {
	id: string;
	projectId: string;
	path: string;
	description: string | null;
	size: number;
	revision: number;
	createdAt: string;
	updatedAt: string;
}

export interface ProjectContextFile extends ProjectContextFileSummary {
	content: string;
}

export interface ProjectDetail extends ProjectTree {
	systemPrompt: string;
	revision: number;
	contextFiles: ProjectContextFileSummary[];
	skillIds: string[];
}

export interface ProjectConfigUpdate {
	systemPrompt: string;
	revision: number;
}

export interface ProjectConfigResponse {
	systemPrompt: string;
	revision: number;
	updatedAt: string;
}

export interface ProjectContextFileCreate {
	path: string;
	content: string;
}

export interface ProjectContextFileUpdate extends ProjectContextFileCreate {
	revision: number;
}

export interface ProjectSkillsResponse {
	skillIds: string[];
	revision: number;
}

export interface ProjectWrite {
	name: string;
	description: string;
	visibility: ResourceVisibility;
	teamIds: string[];
}

export type ProjectPatch = Partial<ProjectWrite>;

export interface ProjectFolderCreate {
	name: string;
	parentId?: string | null;
}

export interface ProjectFolderPatch {
	name?: string;
	parentId?: string | null;
}

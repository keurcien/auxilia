import type { WorkspaceRole } from "@/types/users";

export interface Workspace {
	id: string;
	name: string;
	emoji: string | null;
	color: string | null;
	imageRevision: string | null;
	role: WorkspaceRole;
	createdAt: string;
	updatedAt: string;
}

export interface WorkspaceCreate {
	name: string;
	emoji?: string | null;
	color?: string | null;
}

export interface WorkspacePatch {
	name?: string;
	emoji?: string | null;
	color?: string | null;
}

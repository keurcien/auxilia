/** Workspace role levels, weakest → strongest. */
export type WorkspaceRole = "member" | "editor" | "admin";

export interface User {
	id: string;
	name: string | null;
	firstName: string | null;
	lastName: string | null;
	email: string | null;
	role: WorkspaceRole;
	canCreateWorkspace: boolean;
	canDeleteThreads: boolean;
	isInstanceOwner: boolean;
	teamId: string | null;
	pictureUrl: string | null;
	imageRevision: string | null;
	createdAt: string;
	updatedAt: string;
}

export interface InstanceUserMembership {
	workspaceId: string;
	workspaceName: string;
	role: WorkspaceRole;
	teamId: string | null;
}

export interface InstanceUser {
	id: string;
	name: string | null;
	firstName: string | null;
	lastName: string | null;
	email: string | null;
	canCreateWorkspace: boolean;
	canDeleteThreads: boolean;
	isInstanceOwner: boolean;
	pictureUrl: string | null;
	imageRevision: string | null;
	createdAt: string;
	updatedAt: string;
	memberships: InstanceUserMembership[];
}

export interface UserPromptActivity {
	userId: string;
	lastPromptAt: string | null;
	hasActivePrompt: boolean;
}

/** `GET /users/role-counts`. */
export interface RoleCounts {
	total: number;
	member: number;
	editor: number;
	admin: number;
}

export interface Team {
	id: string;
	name: string;
	color: string | null;
	/** Only meaningful on the list endpoint; create/update responses report 0. */
	memberCount: number;
}

export interface TeamWrite {
	name: string;
	color: string | null;
}

export interface Invite {
	id: string;
	workspaceId: string;
	email: string;
	role: string;
	status: string;
	inviteUrl: string | null;
	invitedBy: string;
	invitedByName: string | null;
	teamId: string | null;
	expiresAt: string;
	createdAt: string;
}

export interface InviteCreate {
	email: string;
	role: WorkspaceRole;
	teamId: string | null;
	workspaceId?: string;
}

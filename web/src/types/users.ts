/** Workspace role levels, weakest → strongest. */
export type WorkspaceRole = "member" | "editor" | "admin";

export interface User {
	id: string;
	name: string | null;
	email: string | null;
	role: WorkspaceRole;
	teamId: string | null;
	pictureUrl: string | null;
	createdAt: string;
	updatedAt: string;
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
	email: string;
	role: string;
	inviteUrl: string;
	invitedByName: string | null;
	createdAt: string;
}

export interface InviteCreate {
	email: string;
	role: WorkspaceRole;
	teamId: string | null;
}

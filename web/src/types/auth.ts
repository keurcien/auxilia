import type { WorkspaceRole } from "@/types/users";

/** `GET /auth/me`. */
export interface CurrentUser {
	id: string;
	name: string | null;
	email: string | null;
	role: WorkspaceRole;
	pictureUrl: string | null;
	createdAt: string;
	updatedAt: string;
}

/** `GET /auth/providers` — which sign-in methods the workspace offers. */
export interface AuthProviders {
	password: boolean;
	google: boolean;
	setupRequired: boolean;
}

/** `GET /auth/invite/{token}` — what an invitee sees before accepting. */
export interface InviteInfo {
	email: string;
	role: string;
	passwordEnabled: boolean;
	googleEnabled: boolean;
}

export interface PersonalAccessToken {
	id: string;
	name: string;
	prefix: string;
	createdAt: string;
}

/** `POST /auth/tokens` — the plaintext is shown once and never stored. */
export interface PersonalAccessTokenCreated extends PersonalAccessToken {
	token: string;
}

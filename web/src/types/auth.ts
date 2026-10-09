import type { WorkspaceRole } from "@/types/users";

/** `GET /auth/me`. */
export interface CurrentUser {
	id: string;
	name: string | null;
	firstName: string | null;
	lastName: string | null;
	email: string | null;
	role: WorkspaceRole;
	workspaceId: string | null;
	canCreateWorkspace: boolean;
	isInstanceOwner: boolean;
	teamId: string | null;
	pictureUrl: string | null;
	imageRevision: string | null;
	twoFactorEnabled: boolean;
	createdAt: string;
	updatedAt: string;
}

/** `GET /auth/providers` — which sign-in methods the workspace offers. */
export interface AuthProviders {
	password: boolean;
	google: boolean;
	setupRequired: boolean;
}

export interface WorkspaceAuthenticationSettings {
	enabled: boolean;
	isConfigured: boolean;
	googleExclusive: boolean;
	clientIdLast4: string | null;
	clientIdLength: number | null;
	callbackUrl: string;
}

export interface WorkspaceAuthenticationUpdate {
	enabled: boolean;
	googleExclusive: boolean;
	clientId?: string;
	clientSecret?: string;
}

export interface SignInResult {
	twoFactorRequired: boolean;
}

/** `GET /auth/invite/{token}` — what an invitee sees before accepting. */
export interface InviteInfo {
	email: string;
	role: string;
	workspaceName: string;
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

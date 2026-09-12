/**
 * Auth resource — `/auth`. Sign-in, first-run setup, invite acceptance, the
 * current user and personal access tokens. The Google OAuth entry point is a
 * browser navigation (`/api/backend/auth/google`), not an API call.
 */
import { api } from "@/lib/api/client";
import type {
	AuthProviders,
	CurrentUser,
	InviteInfo,
	PersonalAccessToken,
	PersonalAccessTokenCreated,
} from "@/types/auth";

export async function getAuthProviders(): Promise<AuthProviders> {
	const response = await api.get<AuthProviders>("/auth/providers");
	return response.data;
}

/** Sets the session cookie on success. */
export async function signIn(email: string, password: string): Promise<void> {
	await api.post("/auth/signin", { email, password });
}

export async function signOut(): Promise<void> {
	await api.post("/auth/signout");
}

export async function getCurrentUser(): Promise<CurrentUser> {
	const response = await api.get<CurrentUser>("/auth/me");
	return response.data;
}

/** First-run: is there an admin yet? */
export async function getSetupStatus(): Promise<{ setupRequired: boolean }> {
	const response = await api.get<{ setupRequired: boolean }>("/auth/setup/status");
	return response.data;
}

/** Create the first admin and sign them in. */
export async function completeSetup(payload: {
	email: string;
	password: string;
	name: string;
}): Promise<void> {
	await api.post("/auth/setup", payload);
}

export async function getInviteInfo(token: string): Promise<InviteInfo> {
	const response = await api.get<InviteInfo>(`/auth/invite/${token}`);
	return response.data;
}

/** Create the invited account and sign it in. */
export async function acceptInvite(payload: {
	token: string;
	password: string;
	name: string;
}): Promise<void> {
	await api.post("/auth/invite/accept", payload);
}

export async function listTokens(): Promise<PersonalAccessToken[]> {
	const response = await api.get<PersonalAccessToken[]>("/auth/tokens");
	return response.data;
}

export async function createToken(name: string): Promise<PersonalAccessTokenCreated> {
	const response = await api.post<PersonalAccessTokenCreated>("/auth/tokens", { name });
	return response.data;
}

export async function deleteToken(tokenId: string): Promise<void> {
	await api.delete(`/auth/tokens/${tokenId}`);
}

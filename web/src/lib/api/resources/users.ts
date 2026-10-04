/**
 * User resource — `/users`. Workspace membership, roles and team assignment.
 * Plain functions over the axios client; failures reject with `ApiError`.
 */
import { api } from "@/lib/api/client";
import type { Paginated } from "@/types/api";
import type { CurrentUser } from "@/types/auth";
import type { RoleCounts, User, WorkspaceRole } from "@/types/users";

export interface UserListParams {
	limit: number;
	offset: number;
	/** Only members holding this role. */
	role?: WorkspaceRole;
	/** Name or email substring. */
	search?: string;
}

export async function listUsers(params: UserListParams): Promise<Paginated<User>> {
	const response = await api.get<Paginated<User>>("/users", { params });
	return response.data;
}

export async function getRoleCounts(): Promise<RoleCounts> {
	const response = await api.get<RoleCounts>("/users/role-counts");
	return response.data;
}

export async function setUserRole(userId: string, role: WorkspaceRole): Promise<void> {
	await api.patch(`/users/${userId}/role`, { role });
}

export async function setUserTeam(userId: string, teamId: string | null): Promise<void> {
	await api.patch(`/users/${userId}/team`, { teamId });
}

export async function setCanCreateWorkspace(
	userId: string,
	canCreateWorkspace: boolean,
): Promise<User> {
	const response = await api.patch<User>(`/users/${userId}`, { canCreateWorkspace });
	return response.data;
}

export async function deleteUser(userId: string): Promise<void> {
	await api.delete(`/users/${userId}`);
}

export async function updateProfile(payload: {
	firstName: string;
	lastName: string;
}): Promise<CurrentUser> {
	const response = await api.patch<CurrentUser>("/users/me", payload);
	return response.data;
}

export async function changePassword(payload: {
	currentPassword: string | null;
	newPassword: string;
}): Promise<void> {
	await api.put("/users/me/password", payload);
}

export function userImageUrl(userId: string, revision: string): string {
	return `/api/backend/users/${userId}/image?v=${encodeURIComponent(revision)}`;
}

export async function uploadProfileImage(file: File): Promise<string> {
	const form = new FormData();
	form.append("file", file);
	const response = await api.put<{ imageRevision: string }>("/users/me/image", form);
	return response.data.imageRevision;
}

export async function deleteProfileImage(): Promise<void> {
	await api.delete("/users/me/image");
}

export interface TwoFactorStatus {
	enabled: boolean;
	backupCodesRemaining: number;
}

export interface TwoFactorSetup {
	secret: string;
	otpauthUri: string;
	qrCodeDataUrl: string;
	setupToken: string;
}

export async function getTwoFactorStatus(): Promise<TwoFactorStatus> {
	const response = await api.get<TwoFactorStatus>("/users/me/two-factor");
	return response.data;
}

export async function beginTwoFactorSetup(
	currentPassword: string | null,
): Promise<TwoFactorSetup> {
	const response = await api.post<TwoFactorSetup>("/users/me/two-factor/setup", {
		currentPassword,
	});
	return response.data;
}

export async function confirmTwoFactorSetup(
	setupToken: string,
	code: string,
): Promise<string[]> {
	const response = await api.post<{ backupCodes: string[] }>(
		"/users/me/two-factor/confirm",
		{ setupToken, code },
	);
	return response.data.backupCodes;
}

export async function disableTwoFactor(payload: {
	currentPassword: string | null;
	code: string;
}): Promise<void> {
	await api.post("/users/me/two-factor/disable", payload);
}

export async function regenerateBackupCodes(payload: {
	currentPassword: string | null;
	code: string;
}): Promise<string[]> {
	const response = await api.post<{ backupCodes: string[] }>(
		"/users/me/two-factor/backup-codes",
		payload,
	);
	return response.data.backupCodes;
}

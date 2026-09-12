/**
 * User resource — `/users`. Workspace membership, roles and team assignment.
 * Plain functions over the axios client; failures reject with `ApiError`.
 */
import { api } from "@/lib/api/client";
import type { Paginated } from "@/types/api";
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

export async function deleteUser(userId: string): Promise<void> {
	await api.delete(`/users/${userId}`);
}

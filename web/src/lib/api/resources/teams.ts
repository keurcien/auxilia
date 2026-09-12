/**
 * Team resource — `/teams/`. Teams group members so they share agents.
 * Plain functions over the axios client; failures reject with `ApiError`.
 */
import { api } from "@/lib/api/client";
import type { Team, TeamWrite } from "@/types/users";

export async function listTeams(): Promise<Team[]> {
	const response = await api.get<Team[]>("/teams/");
	return response.data;
}

export async function createTeam(payload: TeamWrite): Promise<Team> {
	const response = await api.post<Team>("/teams/", payload);
	return response.data;
}

export async function updateTeam(teamId: string, payload: TeamWrite): Promise<Team> {
	const response = await api.patch<Team>(`/teams/${teamId}`, payload);
	return response.data;
}

/** Members keep their account; their `teamId` becomes null (ON DELETE SET NULL). */
export async function deleteTeam(teamId: string): Promise<void> {
	await api.delete(`/teams/${teamId}`);
}

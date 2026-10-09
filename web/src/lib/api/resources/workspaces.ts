import { api } from "@/lib/api/client";
import type {
	Workspace,
	WorkspaceCreate,
	WorkspacePatch,
} from "@/types/workspaces";

export async function listWorkspaces(): Promise<Workspace[]> {
	const response = await api.get<Workspace[]>("/workspaces/");
	return response.data;
}

export async function createWorkspace(payload: WorkspaceCreate): Promise<Workspace> {
	const response = await api.post<Workspace>("/workspaces/", payload);
	return response.data;
}

export async function selectWorkspace(workspaceId: string): Promise<void> {
	await api.post(`/workspaces/${workspaceId}/select`);
}

export async function updateWorkspace(
	workspaceId: string,
	patch: WorkspacePatch,
): Promise<Workspace> {
	const response = await api.patch<Workspace>(`/workspaces/${workspaceId}`, patch);
	return response.data;
}

export async function deleteWorkspace(
	workspaceId: string,
	name: string,
): Promise<{ activeWorkspaceId: string | null }> {
	const response = await api.delete<{ activeWorkspaceId: string | null }>(
		`/workspaces/${workspaceId}`,
		{ data: { name } },
	);
	return response.data;
}

export function workspaceImageUrl(workspaceId: string, revision: string): string {
	return `/api/backend/workspaces/${workspaceId}/image?v=${encodeURIComponent(revision)}`;
}

export async function uploadWorkspaceImage(
	workspaceId: string,
	file: File,
): Promise<string> {
	const form = new FormData();
	form.append("file", file);
	const response = await api.put<{ imageRevision: string }>(
		`/workspaces/${workspaceId}/image`,
		form,
	);
	return response.data.imageRevision;
}

export async function deleteWorkspaceImage(workspaceId: string): Promise<void> {
	await api.delete(`/workspaces/${workspaceId}/image`);
}

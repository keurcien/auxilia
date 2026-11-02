import { api } from "@/lib/api/client";
import type {
	Project,
	ProjectConfigResponse,
	ProjectConfigUpdate,
	ProjectContextFile,
	ProjectContextFileCreate,
	ProjectContextFileSummary,
	ProjectContextFileUpdate,
	ProjectDetail,
	ProjectFolder,
	ProjectFolderCreate,
	ProjectFolderPatch,
	ProjectFolderSearchResult,
	ProjectPatch,
	ProjectSkillsResponse,
	ProjectTree,
	ProjectWrite,
} from "@/types/projects";

export async function listProjects(): Promise<Project[]> {
	const response = await api.get<Project[]>("/projects/");
	return response.data;
}

export async function searchProjects(
	query: string,
	signal?: AbortSignal,
): Promise<Project[]> {
	const response = await api.get<Project[]>("/projects/", {
		params: { query, limit: 20 },
		signal,
	});
	return response.data;
}

export async function getProjectTree(): Promise<ProjectTree[]> {
	const response = await api.get<ProjectTree[]>("/projects/tree");
	return response.data;
}

export async function getProjectDetail(
	projectId: string,
	options: { cookie?: string } = {},
): Promise<ProjectDetail> {
	const response = await api.get<ProjectDetail>(`/projects/${projectId}/detail`, {
		headers: options.cookie ? { Cookie: options.cookie } : undefined,
	});
	return response.data;
}

export async function getSingleProjectTree(
	projectId: string,
): Promise<ProjectTree> {
	const response = await api.get<ProjectTree>(`/projects/${projectId}/tree`);
	return response.data;
}

export async function getProject(projectId: string): Promise<Project> {
	const response = await api.get<Project>(`/projects/${projectId}`);
	return response.data;
}

export async function createProject(payload: ProjectWrite): Promise<Project> {
	const response = await api.post<Project>("/projects/", payload);
	return response.data;
}

export async function updateProject(
	projectId: string,
	payload: ProjectPatch,
): Promise<Project> {
	const response = await api.patch<Project>(`/projects/${projectId}`, payload);
	return response.data;
}

export async function deleteProject(projectId: string): Promise<void> {
	await api.delete(`/projects/${projectId}`);
}

export async function updateProjectConfig(
	projectId: string,
	payload: ProjectConfigUpdate,
): Promise<ProjectConfigResponse> {
	const response = await api.put<ProjectConfigResponse>(
		`/projects/${projectId}/config`,
		payload,
	);
	return response.data;
}

export async function listProjectContextFiles(
	projectId: string,
): Promise<ProjectContextFileSummary[]> {
	const response = await api.get<ProjectContextFileSummary[]>(
		`/projects/${projectId}/context-files`,
	);
	return response.data;
}

export async function createProjectContextFile(
	projectId: string,
	payload: ProjectContextFileCreate,
): Promise<ProjectContextFile> {
	const response = await api.post<ProjectContextFile>(
		`/projects/${projectId}/context-files`,
		payload,
	);
	return response.data;
}

export async function getProjectContextFile(
	fileId: string,
): Promise<ProjectContextFile> {
	const response = await api.get<ProjectContextFile>(
		`/projects/context-files/${fileId}`,
	);
	return response.data;
}

export async function updateProjectContextFile(
	fileId: string,
	payload: ProjectContextFileUpdate,
): Promise<ProjectContextFile> {
	const response = await api.put<ProjectContextFile>(
		`/projects/context-files/${fileId}`,
		payload,
	);
	return response.data;
}

export async function deleteProjectContextFile(
	fileId: string,
	revision: number,
): Promise<void> {
	await api.delete(`/projects/context-files/${fileId}`, {
		params: { revision },
	});
}

export async function getProjectSkills(
	projectId: string,
): Promise<ProjectSkillsResponse> {
	const response = await api.get<ProjectSkillsResponse>(
		`/projects/${projectId}/skills`,
	);
	return response.data;
}

export async function replaceProjectSkills(
	projectId: string,
	skillIds: string[],
	revision: number,
): Promise<ProjectSkillsResponse> {
	const response = await api.put<ProjectSkillsResponse>(
		`/projects/${projectId}/skills`,
		{ skillIds, revision },
	);
	return response.data;
}

export async function createFolder(
	projectId: string,
	payload: ProjectFolderCreate,
): Promise<ProjectFolder> {
	const response = await api.post<ProjectFolder>(
		`/projects/${projectId}/folders`,
		payload,
	);
	return response.data;
}

export async function searchProjectFolders(
	projectId: string,
	query: string,
	signal?: AbortSignal,
): Promise<ProjectFolderSearchResult[]> {
	const response = await api.get<ProjectFolderSearchResult[]>(
		`/projects/${projectId}/folders`,
		{
			params: { query, limit: 20 },
			signal,
		},
	);
	return response.data;
}

export async function updateFolder(
	folderId: string,
	payload: ProjectFolderPatch,
): Promise<ProjectFolder> {
	const response = await api.patch<ProjectFolder>(
		`/projects/folders/${folderId}`,
		payload,
	);
	return response.data;
}

export async function deleteFolder(folderId: string): Promise<void> {
	await api.delete(`/projects/folders/${folderId}`);
}

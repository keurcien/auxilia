import { create } from "zustand";

import { toApiError } from "@/lib/api/errors";
import * as projectsApi from "@/lib/api/resources/projects";
import {
	getWorkspaceGeneration,
	isCurrentWorkspaceGeneration,
} from "@/lib/workspace-generation";
import type {
	Project,
	ProjectConfigUpdate,
	ProjectContextFile,
	ProjectContextFileCreate,
	ProjectContextFileUpdate,
	ProjectDetail,
	ProjectFolder,
	ProjectFolderCreate,
	ProjectFolderPatch,
	ProjectPatch,
	ProjectSkillsResponse,
	ProjectTree,
	ProjectWrite,
} from "@/types/projects";

interface ProjectsState {
	projects: Project[];
	tree: ProjectTree[];
	detailsById: Record<string, ProjectDetail>;
	detailLoadingById: Record<string, boolean>;
	detailAccessLostById: Record<string, boolean>;
	mountedDetailIds: Record<string, number>;
	isInitialized: boolean;
	isLoading: boolean;
	fetchProjects: () => Promise<void>;
	refreshTree: () => Promise<void>;
	setProjectDetail: (detail: ProjectDetail) => void;
	mountProjectDetail: (id: string) => void;
	unmountProjectDetail: (id: string) => void;
	evictProjectDetail: (id: string, accessLost?: boolean) => void;
	fetchProjectDetail: (id: string, force?: boolean) => Promise<ProjectDetail>;
	refreshProjectDetail: (id: string) => Promise<ProjectDetail>;
	updateProjectConfig: (
		id: string,
		payload: ProjectConfigUpdate,
	) => Promise<ProjectDetail>;
	getContextFile: (id: string) => Promise<ProjectContextFile>;
	createContextFile: (
		projectId: string,
		payload: ProjectContextFileCreate,
	) => Promise<ProjectContextFile>;
	updateContextFile: (
		id: string,
		payload: ProjectContextFileUpdate,
	) => Promise<ProjectContextFile>;
	deleteContextFile: (
		projectId: string,
		id: string,
		revision: number,
	) => Promise<void>;
	replaceProjectSkills: (
		projectId: string,
		skillIds: string[],
		revision: number,
	) => Promise<ProjectSkillsResponse>;
	createProject: (payload: ProjectWrite) => Promise<Project>;
	updateProject: (id: string, payload: ProjectPatch) => Promise<Project>;
	deleteProject: (id: string) => Promise<void>;
	createFolder: (
		projectId: string,
		payload: ProjectFolderCreate,
	) => Promise<ProjectFolder>;
	updateFolder: (
		id: string,
		payload: ProjectFolderPatch,
	) => Promise<ProjectFolder>;
	deleteFolder: (id: string) => Promise<void>;
}

let loading: { generation: number; promise: Promise<void> } | null = null;
const detailLoads = new Map<
	string,
	{ generation: number; promise: Promise<ProjectDetail> }
>();

const projectFromTree = (project: ProjectTree): Project => ({
	id: project.id,
	workspaceId: project.workspaceId,
	ownerId: project.ownerId,
	name: project.name,
	emoji: project.emoji,
	description: project.description,
	visibility: project.visibility,
	teamIds: project.teamIds,
	canManage: project.canManage,
	createdAt: project.createdAt,
	updatedAt: project.updatedAt,
});

const contextSummary = ({
	// The detail only retains summaries. File content belongs to the editor draft.
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	content,
	...summary
}: ProjectContextFile) => summary;

export const useProjectsStore = create<ProjectsState>((set, get) => ({
	projects: [],
	tree: [],
	detailsById: {},
	detailLoadingById: {},
	detailAccessLostById: {},
	mountedDetailIds: {},
	isInitialized: false,
	isLoading: false,
	fetchProjects: async () => {
		if (get().isInitialized) return;
		await get().refreshTree();
	},
	refreshTree: async () => {
		const generation = getWorkspaceGeneration();
		if (loading?.generation === generation) return loading.promise;
		set({ isLoading: true });
		const promise: Promise<void> = projectsApi
			.getProjectTree()
			.then((tree) => {
				if (!isCurrentWorkspaceGeneration(generation)) return;
				set((state) => {
					const visibleById = new Map(
						tree.map((project) => [project.id, project]),
					);
					const detailsById = Object.fromEntries(
						Object.entries(state.detailsById)
							.filter(([id]) => visibleById.has(id))
							.map(([id, detail]) => [
								id,
								{ ...detail, ...visibleById.get(id) },
							]),
					);
					const detailAccessLostById = { ...state.detailAccessLostById };
					for (const id of Object.keys(state.detailsById)) {
						if (!visibleById.has(id) && (state.mountedDetailIds[id] ?? 0) > 0) {
							detailAccessLostById[id] = true;
						}
					}
					return {
						tree,
						projects: tree.map(projectFromTree),
						isInitialized: true,
						detailsById,
						detailAccessLostById,
					};
				});
			})
			.catch((error: unknown) => {
				if (isCurrentWorkspaceGeneration(generation)) {
					console.error("Error fetching projects:", error);
				}
				throw error;
			})
			.finally(() => {
				if (loading?.promise === promise) loading = null;
				if (isCurrentWorkspaceGeneration(generation)) {
					set({ isLoading: false });
				}
			});
		loading = { generation, promise };
		return promise;
	},
	setProjectDetail: (detail) => {
		set((state) => ({
			detailsById: { ...state.detailsById, [detail.id]: detail },
			detailAccessLostById: {
				...state.detailAccessLostById,
				[detail.id]: false,
			},
			tree: state.tree.some((project) => project.id === detail.id)
				? state.tree.map((project) =>
						project.id === detail.id ? detail : project,
					)
				: [...state.tree, detail],
			projects: state.projects.some((project) => project.id === detail.id)
				? state.projects.map((project) =>
						project.id === detail.id ? projectFromTree(detail) : project,
					)
				: [...state.projects, projectFromTree(detail)],
		}));
	},
	mountProjectDetail: (id) => {
		set((state) => ({
			mountedDetailIds: {
				...state.mountedDetailIds,
				[id]: (state.mountedDetailIds[id] ?? 0) + 1,
			},
		}));
	},
	unmountProjectDetail: (id) => {
		set((state) => {
			const count = Math.max(0, (state.mountedDetailIds[id] ?? 0) - 1);
			const mountedDetailIds = { ...state.mountedDetailIds };
			if (count === 0) delete mountedDetailIds[id];
			else mountedDetailIds[id] = count;
			return { mountedDetailIds };
		});
	},
	evictProjectDetail: (id, accessLost = false) => {
		set((state) => {
			const detailsById = { ...state.detailsById };
			delete detailsById[id];
			return {
				detailsById,
				detailAccessLostById: {
					...state.detailAccessLostById,
					[id]: accessLost,
				},
			};
		});
	},
	fetchProjectDetail: async (id, force = false) => {
		const cached = get().detailsById[id];
		if (cached && !force) return cached;
		const generation = getWorkspaceGeneration();
		const existing = detailLoads.get(id);
		if (existing?.generation === generation) return existing.promise;
		set((state) => ({
			detailLoadingById: { ...state.detailLoadingById, [id]: true },
		}));
		const promise = projectsApi
			.getProjectDetail(id)
			.then((detail) => {
				if (isCurrentWorkspaceGeneration(generation)) {
					get().setProjectDetail(detail);
				}
				return detail;
			})
			.catch((error: unknown) => {
				const status = toApiError(error).status;
				if (
					isCurrentWorkspaceGeneration(generation) &&
					(status === 403 || status === 404)
				) {
					get().evictProjectDetail(id, true);
				}
				throw error;
			})
			.finally(() => {
				if (detailLoads.get(id)?.promise === promise) detailLoads.delete(id);
				if (isCurrentWorkspaceGeneration(generation)) {
					set((state) => ({
						detailLoadingById: {
							...state.detailLoadingById,
							[id]: false,
						},
					}));
				}
			});
		detailLoads.set(id, { generation, promise });
		return promise;
	},
	refreshProjectDetail: async (id) => get().fetchProjectDetail(id, true),
	updateProjectConfig: async (id, payload) => {
		const generation = getWorkspaceGeneration();
		if (!get().detailsById[id]) throw new Error("Project detail is not loaded");
		const config = await projectsApi.updateProjectConfig(id, payload);
		if (!isCurrentWorkspaceGeneration(generation)) {
			throw new Error("Workspace changed while saving the project");
		}
		let updated: ProjectDetail | null = null;
		set((state) => {
			const latest = state.detailsById[id];
			if (!latest) return state;
			updated = {
				...latest,
				systemPrompt: config.systemPrompt,
				revision: config.revision,
				updatedAt: config.updatedAt,
			};
			return {
				detailsById: {
					...state.detailsById,
					[id]: updated,
				},
				tree: state.tree.map((project) =>
					project.id === id
						? { ...project, updatedAt: config.updatedAt }
						: project,
				),
				projects: state.projects.map((project) =>
					project.id === id
						? { ...project, updatedAt: config.updatedAt }
						: project,
				),
			};
		});
		if (!updated) throw new Error("Project detail is no longer available");
		return updated;
	},
	getContextFile: projectsApi.getProjectContextFile,
	createContextFile: async (projectId, payload) => {
		const generation = getWorkspaceGeneration();
		const file = await projectsApi.createProjectContextFile(projectId, payload);
		if (isCurrentWorkspaceGeneration(generation)) {
			set((state) => {
				const detail = state.detailsById[projectId];
				if (!detail) return state;
				return {
					detailsById: {
						...state.detailsById,
						[projectId]: {
							...detail,
							contextFiles: [
								...detail.contextFiles.filter((item) => item.id !== file.id),
								contextSummary(file),
							].sort((left, right) => left.path.localeCompare(right.path)),
						},
					},
				};
			});
		}
		return file;
	},
	updateContextFile: async (id, payload) => {
		const generation = getWorkspaceGeneration();
		const file = await projectsApi.updateProjectContextFile(id, payload);
		if (isCurrentWorkspaceGeneration(generation)) {
			set((state) => {
				const detail = state.detailsById[file.projectId];
				if (!detail) return state;
				return {
					detailsById: {
						...state.detailsById,
						[file.projectId]: {
							...detail,
							contextFiles: detail.contextFiles
								.map((item) =>
									item.id === file.id ? contextSummary(file) : item,
								)
								.sort((left, right) => left.path.localeCompare(right.path)),
						},
					},
				};
			});
		}
		return file;
	},
	deleteContextFile: async (projectId, id, revision) => {
		const generation = getWorkspaceGeneration();
		await projectsApi.deleteProjectContextFile(id, revision);
		if (!isCurrentWorkspaceGeneration(generation)) return;
		set((state) => {
			const detail = state.detailsById[projectId];
			if (!detail) return state;
			return {
				detailsById: {
					...state.detailsById,
					[projectId]: {
						...detail,
						contextFiles: detail.contextFiles.filter((file) => file.id !== id),
					},
				},
			};
		});
	},
	replaceProjectSkills: async (projectId, skillIds, revision) => {
		const generation = getWorkspaceGeneration();
		const result = await projectsApi.replaceProjectSkills(
			projectId,
			skillIds,
			revision,
		);
		if (isCurrentWorkspaceGeneration(generation)) {
			set((state) => {
				const detail = state.detailsById[projectId];
				if (!detail) return state;
				return {
					detailsById: {
						...state.detailsById,
						[projectId]: {
							...detail,
							skillIds: result.skillIds,
							revision: result.revision,
						},
					},
				};
			});
		}
		return result;
	},
	createProject: async (payload) => {
		const generation = getWorkspaceGeneration();
		const project = await projectsApi.createProject(payload);
		if (isCurrentWorkspaceGeneration(generation)) {
			set((state) => ({
				projects: [...state.projects, project],
				tree: [
					...state.tree,
					{ ...project, folders: [], threads: [], triggers: [] },
				],
			}));
		}
		return project;
	},
	updateProject: async (id, payload) => {
		const generation = getWorkspaceGeneration();
		const project = await projectsApi.updateProject(id, payload);
		if (!isCurrentWorkspaceGeneration(generation)) return project;
		set((state) => ({
			projects: state.projects.map((item) => (item.id === id ? project : item)),
			tree: state.tree.map((item) =>
				item.id === id ? { ...item, ...project } : item,
			),
			detailsById: state.detailsById[id]
				? {
						...state.detailsById,
						[id]: { ...state.detailsById[id], ...project },
					}
				: state.detailsById,
		}));
		return project;
	},
	deleteProject: async (id) => {
		const generation = getWorkspaceGeneration();
		await projectsApi.deleteProject(id);
		if (!isCurrentWorkspaceGeneration(generation)) return;
		set((state) => ({
			projects: state.projects.filter((item) => item.id !== id),
			tree: state.tree.filter((item) => item.id !== id),
			detailsById: Object.fromEntries(
				Object.entries(state.detailsById).filter(([key]) => key !== id),
			),
		}));
	},
	createFolder: async (projectId, payload) => {
		const generation = getWorkspaceGeneration();
		const folder = await projectsApi.createFolder(projectId, payload);
		if (!isCurrentWorkspaceGeneration(generation)) return folder;
		set((state) => ({
			tree: state.tree.map((project) =>
				project.id === projectId
					? { ...project, folders: [...project.folders, folder] }
					: project,
			),
			detailsById: state.detailsById[projectId]
				? {
						...state.detailsById,
						[projectId]: {
							...state.detailsById[projectId],
							folders: [...state.detailsById[projectId].folders, folder],
						},
					}
				: state.detailsById,
		}));
		return folder;
	},
	updateFolder: async (id, payload) => {
		const generation = getWorkspaceGeneration();
		const folder = await projectsApi.updateFolder(id, payload);
		if (!isCurrentWorkspaceGeneration(generation)) return folder;
		set((state) => ({
			tree: state.tree.map((project) =>
				project.id === folder.projectId
					? {
							...project,
							folders: project.folders.map((item) =>
								item.id === id ? folder : item,
							),
						}
					: project,
			),
			detailsById: state.detailsById[folder.projectId]
				? {
						...state.detailsById,
						[folder.projectId]: {
							...state.detailsById[folder.projectId],
							folders: state.detailsById[folder.projectId].folders.map(
								(item) => (item.id === id ? folder : item),
							),
						},
					}
				: state.detailsById,
		}));
		return folder;
	},
	deleteFolder: async (id) => {
		const generation = getWorkspaceGeneration();
		const projectId = Object.values(get().detailsById).find((project) =>
			project.folders.some((folder) => folder.id === id),
		)?.id;
		await projectsApi.deleteFolder(id);
		if (!isCurrentWorkspaceGeneration(generation)) return;
		await get().refreshTree();
		if (projectId) await get().refreshProjectDetail(projectId);
	},
}));

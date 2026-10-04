import { create } from "zustand";

import * as authApi from "@/lib/api/resources/auth";
import * as workspacesApi from "@/lib/api/resources/workspaces";
import { resetWorkspaceStores } from "@/stores/reset-workspace-stores";
import { useUserStore } from "@/stores/user-store";
import type { Workspace, WorkspaceCreate, WorkspacePatch } from "@/types/workspaces";

interface WorkspacesState {
	workspaces: Workspace[];
	activeWorkspaceId: string | null;
	isInitialized: boolean;
	isLoading: boolean;
	isSwitching: boolean;
	error: string | null;
	hydrate: () => Promise<void>;
	createWorkspace: (payload: WorkspaceCreate) => Promise<Workspace>;
	updateWorkspace: (workspaceId: string, patch: WorkspacePatch) => Promise<Workspace>;
	setWorkspaceImageRevision: (workspaceId: string, revision: string | null) => void;
	selectWorkspace: (workspaceId: string) => Promise<void>;
}

let hydration: Promise<void> | null = null;

export const useWorkspacesStore = create<WorkspacesState>((set, get) => ({
	workspaces: [],
	activeWorkspaceId: null,
	isInitialized: false,
	isLoading: false,
	isSwitching: false,
	error: null,
	hydrate: async () => {
		if (get().isInitialized) return;
		if (hydration) return hydration;
		set({ isLoading: true, error: null });
		// The two requests are independent: a failing workspace list must not
		// hide the user (and with it the "Add workspace" entry), and vice versa.
		hydration = Promise.allSettled([
			workspacesApi.listWorkspaces(),
			authApi.getCurrentUser(),
		])
			.then(([workspacesResult, userResult]) => {
				if (userResult.status === "fulfilled") {
					useUserStore.getState().setUser(userResult.value);
					set({ activeWorkspaceId: userResult.value.workspaceId });
				} else {
					console.error("Failed to load current user:", userResult.reason);
				}
				if (workspacesResult.status === "fulfilled") {
					set({ workspaces: workspacesResult.value });
				} else {
					console.error("Failed to load workspaces:", workspacesResult.reason);
				}
				const failed =
					workspacesResult.status === "rejected" || userResult.status === "rejected";
				set({
					error: failed ? "Could not load workspaces." : null,
					isInitialized: !failed,
				});
			})
			.finally(() => {
				hydration = null;
				set({ isLoading: false });
			});
		return hydration;
	},
	createWorkspace: async (payload) => {
		set({ isSwitching: true });
		try {
			const workspace = await workspacesApi.createWorkspace(payload);
			resetWorkspaceStores();
			set((state) => ({
				workspaces: [...state.workspaces, workspace],
				activeWorkspaceId: workspace.id,
				isSwitching: false,
			}));
			return workspace;
		} catch (error) {
			set({ isSwitching: false });
			throw error;
		}
	},
	updateWorkspace: async (workspaceId, patch) => {
		const workspace = await workspacesApi.updateWorkspace(workspaceId, patch);
		set((state) => ({
			workspaces: state.workspaces.map((candidate) =>
				candidate.id === workspaceId ? workspace : candidate,
			),
		}));
		return workspace;
	},
	setWorkspaceImageRevision: (workspaceId, revision) => {
		set((state) => ({
			workspaces: state.workspaces.map((workspace) =>
				workspace.id === workspaceId
					? { ...workspace, imageRevision: revision }
					: workspace,
			),
		}));
	},
	selectWorkspace: async (workspaceId) => {
		if (workspaceId === get().activeWorkspaceId || get().isSwitching) return;
		set({ isSwitching: true });
		try {
			await workspacesApi.selectWorkspace(workspaceId);
			resetWorkspaceStores();
			set({ activeWorkspaceId: workspaceId });
		} catch (error) {
			set({ isSwitching: false });
			throw error;
		}
	},
}));

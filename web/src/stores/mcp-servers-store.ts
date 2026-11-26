import { create } from "zustand";
import {
	MCPServer,
	MCPServerCreate,
	MCPServerUpdate,
} from "@/types/mcp-servers";
import { createOnce } from "@/lib/api/once";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getWorkspaceGeneration, isCurrentWorkspaceGeneration } from "@/lib/workspace-generation";
import { useAgentsStore } from "@/stores/agents-store";

interface McpServersState {
	mcpServers: MCPServer[];
	isInitialized: boolean;
	fetchMcpServers: () => Promise<void>;
	refreshMcpServers: () => Promise<void>;
	createMcpServer: (payload: MCPServerCreate) => Promise<MCPServer>;
	duplicateMcpServer: (id: string) => Promise<MCPServer>;
	updateMcpServer: (id: string, payload: MCPServerUpdate) => Promise<MCPServer>;
	applyMcpServer: (server: MCPServer) => void;
	deleteMcpServer: (id: string, options?: { detachAgents?: boolean }) => Promise<void>;
	resetMcpServerConnections: (id: string) => Promise<void>;
}

/** Mutations own their cache update: callers state intent, never mirror HTTP results. */
export const useMcpServersStore = create<McpServersState>((set, get) => {
	const load = createOnce(async () => {
		const generation = getWorkspaceGeneration();
		try {
			const servers = await mcpServersApi.listMcpServers();
			if (isCurrentWorkspaceGeneration(generation)) {
				set({ mcpServers: servers, isInitialized: true });
			}
		} catch (error) {
			if (!isCurrentWorkspaceGeneration(generation)) return;
			console.error("Error fetching MCP servers:", error);
			throw error;
		}
	});

	return {
		mcpServers: [],
		isInitialized: false,
		fetchMcpServers: async () => {
			if (get().isInitialized) {
				return;
			}
			return load.run();
		},
		refreshMcpServers: () => load.refresh(),
		createMcpServer: async (payload) => {
			const created = await mcpServersApi.createMcpServer(payload);
			set((state) => ({ mcpServers: [created, ...state.mcpServers] }));
			return created;
		},
		duplicateMcpServer: async (id) => {
			const created = await mcpServersApi.duplicateMcpServer(id);
			set((state) => ({ mcpServers: [created, ...state.mcpServers] }));
			return created;
		},
		updateMcpServer: async (id, payload) => {
			const updated = await mcpServersApi.updateMcpServer(id, payload);
			set((state) => ({
				mcpServers: state.mcpServers.map((server) =>
					server.id === id ? updated : server,
				),
			}));
			return updated;
		},
		applyMcpServer: (updated) => {
			set((state) => ({
				mcpServers: state.mcpServers.map((server) =>
					server.id === updated.id ? updated : server,
				),
			}));
		},
		deleteMcpServer: async (id, options) => {
			await mcpServersApi.deleteMcpServer(id, options);
			set((state) => ({
				mcpServers: state.mcpServers.filter((server) => server.id !== id),
			}));
			useAgentsStore.getState().removeMcpServerBinding(id);
		},
		resetMcpServerConnections: async (id) => {
			await mcpServersApi.resetMcpServerConnections(id);
		},
	};
});

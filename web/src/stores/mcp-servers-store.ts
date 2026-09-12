import { create } from "zustand";
import {
	MCPServer,
	MCPServerCreate,
	MCPServerUpdate,
} from "@/types/mcp-servers";
import { createOnce } from "@/lib/api/once";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";

interface McpServersState {
	mcpServers: MCPServer[];
	isInitialized: boolean;
	fetchMcpServers: () => Promise<void>;
	createMcpServer: (payload: MCPServerCreate) => Promise<MCPServer>;
	updateMcpServer: (id: string, payload: MCPServerUpdate) => Promise<MCPServer>;
	deleteMcpServer: (id: string, options?: { detachAgents?: boolean }) => Promise<void>;
	resetMcpServerConnections: (id: string) => Promise<void>;
}

/** Mutations own their cache update: callers state intent, never mirror HTTP results. */
export const useMcpServersStore = create<McpServersState>((set, get) => {
	const load = createOnce(async () => {
		try {
			const servers = await mcpServersApi.listMcpServers();
			set({ mcpServers: servers, isInitialized: true });
		} catch (error) {
			console.error("Error fetching MCP servers:", error);
			set({ isInitialized: true });
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
		createMcpServer: async (payload) => {
			const created = await mcpServersApi.createMcpServer(payload);
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
		deleteMcpServer: async (id, options) => {
			await mcpServersApi.deleteMcpServer(id, options);
			set((state) => ({
				mcpServers: state.mcpServers.filter((server) => server.id !== id),
			}));
		},
		resetMcpServerConnections: async (id) => {
			await mcpServersApi.resetMcpServerConnections(id);
		},
	};
});

import { create } from "zustand";
import {
	MCPServer,
	MCPServerCreate,
	MCPServerUpdate,
} from "@/types/mcp-servers";
import { api } from "@/lib/api/client";

interface McpServersState {
	mcpServers: MCPServer[];
	isInitialized: boolean;
	fetchMcpServers: () => Promise<void>;
	createMcpServer: (payload: MCPServerCreate) => Promise<MCPServer>;
	updateMcpServer: (id: string, payload: MCPServerUpdate) => Promise<MCPServer>;
	deleteMcpServer: (id: string) => Promise<void>;
	resetMcpServerConnections: (id: string) => Promise<void>;
}

export const useMcpServersStore = create<McpServersState>((set, get) => ({
	mcpServers: [],
	isInitialized: false,
	fetchMcpServers: async () => {
		if (get().isInitialized) {
			return;
		}

		try {
			const response = await api.get("/mcp-servers");
			set({ mcpServers: response.data, isInitialized: true });
		} catch (error) {
			console.error("Error fetching MCP servers:", error);
			set({ isInitialized: true });
			throw error;
		}
	},
	createMcpServer: async (payload) => {
		const response = await api.post("/mcp-servers", payload);
		const created: MCPServer = response.data;
		set((state) => ({ mcpServers: [created, ...state.mcpServers] }));
		return created;
	},
	updateMcpServer: async (id, payload) => {
		const response = await api.patch(`/mcp-servers/${id}`, payload);
		const updated: MCPServer = response.data;
		set((state) => ({
			mcpServers: state.mcpServers.map((server) =>
				server.id === id ? updated : server,
			),
		}));
		return updated;
	},
	deleteMcpServer: async (id) => {
		await api.delete(`/mcp-servers/${id}`);
		set((state) => ({
			mcpServers: state.mcpServers.filter((server) => server.id !== id),
		}));
	},
	resetMcpServerConnections: async (id) => {
		await api.post(`/mcp-servers/${id}/reset`);
	},
}));

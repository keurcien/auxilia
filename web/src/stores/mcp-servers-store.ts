import { create } from "zustand";
import { MCPServer } from "@/types/mcp-servers";
import { api } from "@/lib/api/client";

interface McpServersState {
	mcpServers: MCPServer[];
	isInitialized: boolean;
	fetchMcpServers: () => Promise<void>;
	addMcpServer: (mcpServer: MCPServer) => void;
	updateMcpServer: (mcpServerId: string, mcpServer: MCPServer) => void;
	removeMcpServer: (mcpServerId: string) => void;
}

export const useMcpServersStore = create<McpServersState>((set, get) => ({
	mcpServers: [],
	isInitialized: false,
	fetchMcpServers: async () => {
		// Only fetch if not already initialized
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
	addMcpServer: (mcpServer) =>
		set((state) => ({ mcpServers: [mcpServer, ...state.mcpServers] })),
	updateMcpServer: (mcpServerId, mcpServer) =>
		set((state) => ({
			mcpServers: state.mcpServers.map((server) =>
				server.id === mcpServerId ? mcpServer : server
			),
		})),
	removeMcpServer: (mcpServerId) =>
		set((state) => ({
			mcpServers: state.mcpServers.filter(
				(server) => server.id !== mcpServerId
			),
		})),
}));

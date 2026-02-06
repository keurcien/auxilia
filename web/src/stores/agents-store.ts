import { create } from "zustand";
import { Agent } from "@/types/agents";
import { api } from "@/lib/api/client";

interface AgentsState {
	agents: Agent[];
	isInitialized: boolean;
	fetchAgents: () => Promise<void>;
	addAgent: (agent: Agent) => void;
	updateAgent: (agentId: string, agent: Agent) => void;
	removeAgent: (agentId: string) => void;
}

export const useAgentsStore = create<AgentsState>((set, get) => ({
	agents: [],
	isInitialized: false,
	fetchAgents: async () => {
		if (get().isInitialized) {
			return;
		}

		try {
			const response = await api.get("/agents");
			set({ agents: response.data, isInitialized: true });
		} catch (error) {
			console.error("Error fetching agents:", error);
			set({ isInitialized: true });
			throw error;
		}
	},
	addAgent: (agent) => set((state) => ({ agents: [agent, ...state.agents] })),
	updateAgent: (agentId, agent) =>
		set((state) => ({
			agents: state.agents.map((a) => (a.id === agentId ? { ...a, ...agent } : a)),
		})),
	removeAgent: (agentId) =>
		set((state) => ({
			agents: state.agents.filter((agent) => agent.id !== agentId),
		})),
}));

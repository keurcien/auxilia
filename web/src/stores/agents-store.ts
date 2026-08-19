import { create } from "zustand";
import { Agent, AgentTag } from "@/types/agents";
import { api } from "@/lib/api/client";

interface AgentsState {
	agents: Agent[];
	isInitialized: boolean;
	fetchAgents: () => Promise<void>;
	refreshAgents: () => Promise<void>;
	addAgent: (agent: Agent) => void;
	updateAgent: (agentId: string, agent: Partial<Agent>) => void;
	removeAgent: (agentId: string) => void;
	applyTagUpdate: (tag: AgentTag) => void;
	applyTagRemoval: (tagId: string) => void;
}

// Shared across callers so concurrent mounts (sidebar + list page) coalesce
// into a single /agents request instead of racing before isInitialized flips.
let inflight: Promise<void> | null = null;

export const useAgentsStore = create<AgentsState>((set, get) => ({
	agents: [],
	isInitialized: false,
	fetchAgents: async () => {
		if (get().isInitialized) {
			return;
		}
		if (inflight) {
			return inflight;
		}
		return get().refreshAgents();
	},
	refreshAgents: async () => {
		const load = async () => {
			try {
				const response = await api.get("/agents");
				set({ agents: response.data, isInitialized: true });
			} catch (error) {
				console.error("Error fetching agents:", error);
				set({ isInitialized: true });
				throw error;
			}
		};
		// A refresh must observe server state from after the caller's mutation,
		// so it never joins a request that may have started earlier — it queues
		// a fresh GET behind any in-flight one instead.
		const next = inflight ? inflight.catch(() => {}).then(load) : load();
		inflight = next;
		try {
			await next;
		} finally {
			if (inflight === next) {
				inflight = null;
			}
		}
	},
	addAgent: (agent) => { set((state) => ({ agents: [agent, ...state.agents] })); },
	updateAgent: (agentId, agent) =>
		{ set((state) => ({
			agents: state.agents.map((a) => (a.id === agentId ? { ...a, ...agent } : a)),
		})); },
	removeAgent: (agentId) =>
		{ set((state) => ({
			agents: state.agents.filter((agent) => agent.id !== agentId),
		})); },
	// Tags are a shared vocabulary: renaming or deleting one affects every
	// agent carrying it, not just the agent whose dialog made the change.
	applyTagUpdate: (tag) =>
		{ set((state) => ({
			agents: state.agents.map((a) =>
				a.tag?.id === tag.id ? { ...a, tag } : a,
			),
		})); },
	applyTagRemoval: (tagId) =>
		{ set((state) => ({
			agents: state.agents.map((a) =>
				a.tag?.id === tagId ? { ...a, tag: null } : a,
			),
		})); },
}));

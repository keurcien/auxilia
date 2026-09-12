import { create } from "zustand";
import { Agent, AgentTag } from "@/types/agents";
import { createOnce } from "@/lib/api/once";
import * as agentsApi from "@/lib/api/resources/agents";
import type { AgentWrite } from "@/lib/api/resources/agents";

interface AgentsState {
	agents: Agent[];
	isInitialized: boolean;
	/** Load once; concurrent callers share the in-flight request. */
	fetchAgents: () => Promise<void>;
	/** Load again, after any in-flight load settles. */
	refreshAgents: () => Promise<void>;
	/** Re-read one agent from the server and merge it into the list. */
	refreshAgent: (agentId: string) => Promise<void>;

	// --- mutations: each owns its HTTP call *and* its cache update ---------
	createAgent: (payload: AgentWrite) => Promise<Agent>;
	saveAgentConfig: (agentId: string, payload: AgentWrite) => Promise<Agent>;
	/** Soft delete: the agent leaves the live list. */
	archiveAgent: (agentId: string) => Promise<void>;
	/** Un-archive: the live list is reloaded so the agent reappears in place. */
	restoreAgent: (agentId: string) => Promise<void>;
	permanentlyDeleteAgent: (agentId: string) => Promise<void>;
	setAgentTag: (agentId: string, tagId: string | null) => Promise<Agent>;

	// --- local cache edits, for callers whose HTTP call lives elsewhere ------
	addAgent: (agent: Agent) => void;
	updateAgent: (agentId: string, agent: Partial<Agent>) => void;
	removeAgent: (agentId: string) => void;
	applyTagUpdate: (tag: AgentTag) => void;
	applyTagRemoval: (tagId: string) => void;
}

export const useAgentsStore = create<AgentsState>((set, get) => {
	const loader = createOnce(async () => {
		try {
			const agents = await agentsApi.listAgents();
			set({ agents, isInitialized: true });
		} catch (error) {
			console.error("Error fetching agents:", error);
			set({ isInitialized: true });
			throw error;
		}
	});

	return {
		agents: [],
		isInitialized: false,
		fetchAgents: async () => {
			if (get().isInitialized) return;
			await loader.run();
		},
		refreshAgents: () => loader.refresh(),
		refreshAgent: async (agentId) => {
			const agent = await agentsApi.getAgent(agentId);
			get().updateAgent(agentId, agent);
		},

		createAgent: async (payload) => {
			const created = await agentsApi.createAgent(payload);
			get().addAgent(created);
			return created;
		},
		saveAgentConfig: async (agentId, payload) => {
			const saved = await agentsApi.saveAgentConfig(agentId, payload);
			get().updateAgent(agentId, saved);
			return saved;
		},
		archiveAgent: async (agentId) => {
			await agentsApi.archiveAgent(agentId);
			get().removeAgent(agentId);
		},
		restoreAgent: async (agentId) => {
			await agentsApi.restoreAgent(agentId);
			await loader.refresh().catch(() => {});
		},
		permanentlyDeleteAgent: async (agentId) => {
			await agentsApi.permanentlyDeleteAgent(agentId);
			get().removeAgent(agentId);
		},
		setAgentTag: async (agentId, tagId) => {
			const updated = await agentsApi.patchAgent(agentId, { tagId });
			get().updateAgent(agentId, updated);
			return updated;
		},

		addAgent: (agent) => {
			set((state) => ({ agents: [agent, ...state.agents] }));
		},
		updateAgent: (agentId, agent) => {
			set((state) => ({
				agents: state.agents.map((a) => (a.id === agentId ? { ...a, ...agent } : a)),
			}));
		},
		removeAgent: (agentId) => {
			set((state) => ({
				agents: state.agents.filter((agent) => agent.id !== agentId),
			}));
		},
		applyTagUpdate: (tag) => {
			set((state) => ({
				agents: state.agents.map((a) => (a.tag?.id === tag.id ? { ...a, tag } : a)),
			}));
		},
		applyTagRemoval: (tagId) => {
			set((state) => ({
				agents: state.agents.map((a) => (a.tag?.id === tagId ? { ...a, tag: null } : a)),
			}));
		},
	};
});

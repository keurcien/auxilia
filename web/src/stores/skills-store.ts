import { create } from "zustand";
import {
	Skill,
	SkillDiff,
	SkillSave,
	SkillSource,
	SkillSourceCreate,
	SkillSourcePreview,
	SkillSummary,
} from "@/types/skills";
import { api } from "@/lib/api/client";

interface SkillsState {
	skills: SkillSummary[];
	isInitialized: boolean;
	fetchSkills: (force?: boolean) => Promise<void>;
	getSkill: (id: string) => Promise<Skill>;
	createSkill: (payload: SkillSave) => Promise<Skill>;
	importSkill: (file: File) => Promise<Skill>;
	updateSkill: (id: string, payload: SkillSave) => Promise<Skill>;
	deleteSkill: (id: string) => Promise<void>;
	/** Sourced skills: what the newest synced version changes, and adopting it. */
	getSkillDiff: (id: string) => Promise<SkillDiff>;
	adoptSkill: (id: string) => Promise<Skill>;
	/** Repositories the workspace syncs skills from. */
	sources: SkillSource[];
	sourcesInitialized: boolean;
	fetchSources: (force?: boolean) => Promise<void>;
	previewSource: (payload: SkillSourceCreate) => Promise<SkillSourcePreview>;
	createSource: (payload: SkillSourceCreate) => Promise<SkillSource>;
	syncSource: (id: string) => Promise<SkillSource>;
	deleteSource: (id: string) => Promise<void>;
}

const summaryOf = (skill: Skill): SkillSummary => {
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	const { content, files, agents, available, ...summary } = skill;
	return summary;
};

export const useSkillsStore = create<SkillsState>((set, get) => ({
	skills: [],
	isInitialized: false,
	fetchSkills: async (force = false) => {
		if (get().isInitialized && !force) {
			return;
		}
		try {
			const response = await api.get("/skills");
			set({ skills: response.data as SkillSummary[], isInitialized: true });
		} catch (error) {
			set({ isInitialized: true });
			throw error;
		}
	},
	getSkill: async (id) => {
		const response = await api.get(`/skills/${id}`);
		return response.data as Skill;
	},
	createSkill: async (payload) => {
		const response = await api.post("/skills", payload);
		const created = response.data as Skill;
		set((state) => ({ skills: [summaryOf(created), ...state.skills] }));
		return created;
	},
	importSkill: async (file) => {
		const form = new FormData();
		form.append("file", file);
		const response = await api.post("/skills/import", form);
		const created = response.data as Skill;
		set((state) => ({ skills: [summaryOf(created), ...state.skills] }));
		return created;
	},
	updateSkill: async (id, payload) => {
		const response = await api.put(`/skills/${id}`, payload);
		const updated = response.data as Skill;
		set((state) => ({
			skills: [
				summaryOf(updated),
				...state.skills.filter((skill) => skill.id !== id),
			],
		}));
		return updated;
	},
	deleteSkill: async (id) => {
		await api.delete(`/skills/${id}`);
		set((state) => ({
			skills: state.skills.filter((skill) => skill.id !== id),
		}));
	},
	getSkillDiff: async (id) => {
		const response = await api.get(`/skills/${id}/diff`);
		return response.data as SkillDiff;
	},
	adoptSkill: async (id) => {
		const response = await api.post(`/skills/${id}/adopt`);
		const adopted = response.data as Skill;
		set((state) => ({
			skills: state.skills.map((skill) => (skill.id === id ? summaryOf(adopted) : skill)),
		}));
		return adopted;
	},
	sources: [],
	sourcesInitialized: false,
	fetchSources: async (force = false) => {
		if (get().sourcesInitialized && !force) {
			return;
		}
		try {
			const response = await api.get("/skills/sources");
			set({ sources: response.data as SkillSource[], sourcesInitialized: true });
		} catch (error) {
			set({ sourcesInitialized: true });
			throw error;
		}
	},
	previewSource: async (payload) => {
		const response = await api.post("/skills/sources/preview", payload);
		return response.data as SkillSourcePreview;
	},
	createSource: async (payload) => {
		const response = await api.post("/skills/sources", payload);
		const created = response.data as SkillSource;
		set((state) => ({ sources: [...state.sources, created] }));
		// The sync that ran on creation changed the library.
		await get().fetchSkills(true);
		return created;
	},
	syncSource: async (id) => {
		const response = await api.post(`/skills/sources/${id}/sync`);
		const synced = response.data as SkillSource;
		set((state) => ({
			sources: state.sources.map((source) => (source.id === id ? synced : source)),
		}));
		await get().fetchSkills(true);
		return synced;
	},
	deleteSource: async (id) => {
		await api.delete(`/skills/sources/${id}`);
		set((state) => ({
			sources: state.sources.filter((source) => source.id !== id),
		}));
		await get().fetchSkills(true);
	},
}));

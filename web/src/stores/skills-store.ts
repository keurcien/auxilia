import { create } from "zustand";
import {
	Skill,
	SkillDiff,
	SkillSave,
	SkillSource,
	SkillSourceCreate,
	SkillSourcePreview,
	SkillSyncPlan,
	SkillSummary,
} from "@/types/skills";
import * as skillsApi from "@/lib/api/resources/skills";

interface SkillsState {
	skills: SkillSummary[];
	isInitialized: boolean;
	fetchSkills: (force?: boolean) => Promise<void>;
	getSkill: (id: string) => Promise<Skill>;
	createSkill: (payload: SkillSave) => Promise<Skill>;
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
	/** What the next sync would change; reads the repository, writes nothing. */
	planSync: (id: string) => Promise<SkillSyncPlan>;
	syncSource: (id: string) => Promise<SkillSource>;
	deleteSource: (id: string) => Promise<void>;
}

const summaryOf = (skill: Skill): SkillSummary => {
	// `agents` stays: the library row renders it as an avatar stack.
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	const { content, files, available, ...summary } = skill;
	return summary;
};

/**
 * Whichever library/source load started last is the only one allowed to
 * land. `fetchSkills(true)` runs after every mutation, so without this an
 * in-flight load started earlier could resolve afterwards and reinstate the
 * list as it was before the mutation — the skill you just deleted coming
 * back, the source you just synced showing its old revision.
 */
let skillsLoad = 0;
let sourcesLoad = 0;

export const useSkillsStore = create<SkillsState>((set, get) => ({
	skills: [],
	isInitialized: false,
	fetchSkills: async (force = false) => {
		if (get().isInitialized && !force) {
			return;
		}
		const ticket = ++skillsLoad;
		try {
			const skills = await skillsApi.listSkills();
			if (ticket === skillsLoad) set({ skills, isInitialized: true });
			else set({ isInitialized: true });
		} catch (error) {
			// Deliberately *not* marking it initialized: a failed load that
			// claimed to be done left the nav count at 0 and made every later
			// page skip its own fetch, so the list never recovered.
			throw error;
		}
	},
	getSkill: async (id) => {
		return skillsApi.getSkill(id);
	},
	createSkill: async (payload) => {
		const created = await skillsApi.createSkill(payload);
		set((state) => ({ skills: [summaryOf(created), ...state.skills] }));
		return created;
	},
	updateSkill: async (id, payload) => {
		const updated = await skillsApi.updateSkill(id, payload);
		set((state) => ({
			skills: [
				summaryOf(updated),
				...state.skills.filter((skill) => skill.id !== id),
			],
		}));
		return updated;
	},
	deleteSkill: async (id) => {
		await skillsApi.deleteSkill(id);
		set((state) => ({
			skills: state.skills.filter((skill) => skill.id !== id),
		}));
	},
	getSkillDiff: async (id) => {
		return skillsApi.getSkillDiff(id);
	},
	adoptSkill: async (id) => {
		const adopted = await skillsApi.adoptSkill(id);
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
		const ticket = ++sourcesLoad;
		try {
			const sources = await skillsApi.listSkillSources();
			if (ticket === sourcesLoad) set({ sources, sourcesInitialized: true });
			else set({ sourcesInitialized: true });
		} catch (error) {
			// Deliberately *not* marking it initialized: a failed load that
			// claimed to be done left the nav count at 0 and made every later
			// page skip its own fetch, so the list never recovered.
			throw error;
		}
	},
	previewSource: async (payload) => {
		return skillsApi.previewSkillSource(payload);
	},
	createSource: async (payload) => {
		const created = await skillsApi.createSkillSource(payload);
		set((state) => ({ sources: [...state.sources, created] }));
		// The sync that ran on creation changed the library.
		await get().fetchSkills(true);
		return created;
	},
	planSync: async (id) => {
		return skillsApi.planSkillSourceSync(id);
	},
	syncSource: async (id) => {
		const synced = await skillsApi.syncSkillSource(id);
		set((state) => ({
			sources: state.sources.map((source) => (source.id === id ? synced : source)),
		}));
		await get().fetchSkills(true);
		return synced;
	},
	deleteSource: async (id) => {
		await skillsApi.deleteSkillSource(id);
		set((state) => ({
			sources: state.sources.filter((source) => source.id !== id),
		}));
		await get().fetchSkills(true);
	},
}));

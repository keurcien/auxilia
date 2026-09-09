import { create } from "zustand";
import { Skill, SkillSave, SkillSummary } from "@/types/skills";
import { api } from "@/lib/api/client";

interface SkillsState {
	skills: SkillSummary[];
	isInitialized: boolean;
	fetchSkills: () => Promise<void>;
	getSkill: (id: string) => Promise<Skill>;
	createSkill: (payload: SkillSave) => Promise<Skill>;
	importSkill: (file: File) => Promise<Skill>;
	updateSkill: (id: string, payload: SkillSave) => Promise<Skill>;
	deleteSkill: (id: string) => Promise<void>;
}

const summaryOf = (skill: Skill): SkillSummary => {
	// eslint-disable-next-line @typescript-eslint/no-unused-vars
	const { content, files, ...summary } = skill;
	return summary;
};

export const useSkillsStore = create<SkillsState>((set, get) => ({
	skills: [],
	isInitialized: false,
	fetchSkills: async () => {
		if (get().isInitialized) {
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
}));

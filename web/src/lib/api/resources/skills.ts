/**
 * Skill resource — `/skills`: the workspace's skill library, and the
 * repositories it syncs from (`/skills/sources`).
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 *
 * The source routes are declared on `""`, not `"/"` — the Next proxy 308s a
 * trailing slash away and FastAPI would then match `/skills/{skill_id}`.
 */
import { api } from "@/lib/api/client";
import type {
	Skill,
	SkillDiff,
	SkillSave,
	SkillSource,
	SkillSourceCreate,
	SkillSourcePreview,
	SkillSummary,
	SkillSyncPlan,
} from "@/types/skills";

// -- the library -------------------------------------------------------------

/** Every skill in the workspace. Never carries the document or its files. */
export async function listSkills(): Promise<SkillSummary[]> {
	const response = await api.get<SkillSummary[]>("/skills");
	return response.data;
}

/** One skill, with its SKILL.md, its files and the agents using it. */
export async function getSkill(skillId: string): Promise<Skill> {
	const response = await api.get<Skill>(`/skills/${skillId}`);
	return response.data;
}

export async function createSkill(payload: SkillSave): Promise<Skill> {
	const response = await api.post<Skill>("/skills", payload);
	return response.data;
}

/** Refused with a 409 when `payload.revision` is not the current one. */
export async function updateSkill(
	skillId: string,
	payload: SkillSave,
): Promise<Skill> {
	const response = await api.put<Skill>(`/skills/${skillId}`, payload);
	return response.data;
}

export async function deleteSkill(skillId: string): Promise<void> {
	await api.delete(`/skills/${skillId}`);
}

/** What adopting the newest synced version of a sourced skill would change. */
export async function getSkillDiff(skillId: string): Promise<SkillDiff> {
	const response = await api.get<SkillDiff>(`/skills/${skillId}/diff`);
	return response.data;
}

/** Apply that newest version — the only way a sourced skill changes. */
export async function adoptSkill(skillId: string): Promise<Skill> {
	const response = await api.post<Skill>(`/skills/${skillId}/adopt`);
	return response.data;
}

// -- the repositories they come from -----------------------------------------

export async function listSkillSources(): Promise<SkillSource[]> {
	const response = await api.get<SkillSource[]>("/skills/sources");
	return response.data;
}

/** Read a repository without saving anything — the "test before adding" step. */
export async function previewSkillSource(
	payload: SkillSourceCreate,
): Promise<SkillSourcePreview> {
	const response = await api.post<SkillSourcePreview>(
		"/skills/sources/preview",
		payload,
	);
	return response.data;
}

export async function createSkillSource(
	payload: SkillSourceCreate,
): Promise<SkillSource> {
	const response = await api.post<SkillSource>("/skills/sources", payload);
	return response.data;
}

/** What the next sync would change. Reads the repository, writes nothing. */
export async function planSkillSourceSync(
	sourceId: string,
): Promise<SkillSyncPlan> {
	const response = await api.get<SkillSyncPlan>(
		`/skills/sources/${sourceId}/plan`,
	);
	return response.data;
}

export async function syncSkillSource(sourceId: string): Promise<SkillSource> {
	const response = await api.post<SkillSource>(
		`/skills/sources/${sourceId}/sync`,
	);
	return response.data;
}

/** Disconnecting keeps the skills; they become in-app skills. */
export async function deleteSkillSource(sourceId: string): Promise<void> {
	await api.delete(`/skills/sources/${sourceId}`);
}

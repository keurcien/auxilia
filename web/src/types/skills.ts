export type SkillFileEncoding = "utf-8" | "base64";

/** A supporting file of a skill, relative to the skill folder. */
export interface SkillFile {
	path: string;
	content: string;
	encoding: SkillFileEncoding;
}

/** A library row — `GET /skills` never carries the document or its files. */
export interface SkillSummary {
	id: string;
	ownerId: string;
	name: string;
	description: string;
	revision: number;
	fileCount: number;
	updatedAt: string;
	canEdit: boolean;
}

/** The full skill — `GET /skills/{id}` and every save result. */
export interface Skill extends SkillSummary {
	/** The whole SKILL.md, frontmatter included. */
	content: string;
	files: SkillFile[];
}

export interface SkillSave {
	content: string;
	files: SkillFile[];
	/** The revision the editor loaded; required on update, refused when stale. */
	revision?: number;
}

/** A skill enabled on an agent, as the agent detail response lists it. */
export interface AgentSkill {
	id: string;
	name: string;
	description: string;
}

/** Same rule as the backend (`app/skills/schemas.py`) and the Agent Skills spec. */
export const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const SKILL_NAME_MAX = 64;
export const SKILL_DESCRIPTION_MAX = 1024;

export interface SkillFile {
	path: string;
	content: string;
	encoding: "utf-8" | "base64";
}
export interface Skill {
	id: string;
	ownerId: string;
	revision: number;
	name: string;
	description: string;
	/** SKILL.md body — everything after the frontmatter. */
	instructions: string;
	/** The full SKILL.md, frontmatter included. */
	content: string;
	files: SkillFile[];
	canEdit: boolean;
}
export interface SkillAttachment {
	skillId: string;
	name: string;
}

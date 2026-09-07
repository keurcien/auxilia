export interface SkillFile {
	path: string;
	content: string;
	encoding: "utf-8" | "base64";
}
export interface Skill {
	id: string;
	ownerId: string;
	visibility: "private" | "workspace";
	revision: number;
	name: string;
	description: string;
	content: string;
	files: SkillFile[];
	canEdit: boolean;
}
export interface SkillAttachment {
	skillId: string;
	name: string;
}

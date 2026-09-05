export interface SkillFile {
	path: string;
	content: string;
	encoding: "utf-8" | "base64";
}
export interface SkillBundle {
	name: string;
	title: string;
	description: string;
	instructions: string;
	requiresCode: boolean;
	requiredMcpServerIds: string[];
	files: SkillFile[];
	examples: { prompt: string; expected: string }[];
	changeSummary: string;
}
export interface SkillVersion {
	id: string;
	number: number;
	bundle: SkillBundle;
	createdAt: string;
}
export interface Skill {
	id: string;
	ownerId: string;
	visibility: "private" | "workspace";
	revision: number;
	draft: SkillBundle;
	canEdit: boolean;
	versions: SkillVersion[];
	usedBy: string[];
}
export interface SkillAttachment {
	skillId: string;
	versionId: string;
	number: number;
	title: string;
	missing: string[];
}

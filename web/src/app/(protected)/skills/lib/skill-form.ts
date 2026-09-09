import { Skill, SkillFile } from "@/types/skills";

/** The draft the skill editor works on: structured fields, not raw YAML. */
export interface SkillFormState {
	name: string;
	description: string;
	instructions: string;
	files: SkillFile[];
}

/** Same rule as the backend `SkillBundle.name` pattern. */
export const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export function defaultSkillForm(): SkillFormState {
	return { name: "", description: "", instructions: "", files: [] };
}

export function fromSkill(skill: Skill): SkillFormState {
	return {
		name: skill.name,
		description: skill.description,
		instructions: skill.instructions,
		files: skill.files.map((f) => ({ ...f })),
	};
}

export function isFormDirty(a: SkillFormState, b: SkillFormState): boolean {
	return JSON.stringify(a) !== JSON.stringify(b);
}

export function isValidSkillName(name: string): boolean {
	return name.length <= 64 && SKILL_NAME_PATTERN.test(name);
}

/**
 * A YAML plain scalar is only safe for tame strings; anything with YAML
 * punctuation, a reserved word, or a numeric look is emitted double-quoted.
 * JSON string escaping is a valid YAML double-quoted scalar.
 */
export function yamlScalar(value: string): string {
	const plainSafe =
		/^[A-Za-z][A-Za-z0-9 _.,;!?'()\/-]*$/.test(value) &&
		!/\s$/.test(value) &&
		!/^(true|false|yes|no|on|off|null|y|n)$/i.test(value);
	return plainSafe ? value : JSON.stringify(value);
}

/** Build the SKILL.md the backend parses from the structured fields. */
export function composeSkillMarkdown(form: SkillFormState): string {
	const frontmatter = [
		"---",
		`name: ${yamlScalar(form.name)}`,
		`description: ${yamlScalar(form.description)}`,
		"---",
	].join("\n");
	return `${frontmatter}\n\n${form.instructions.trim()}\n`;
}

export function toPayload(form: SkillFormState, revision?: number) {
	return {
		content: composeSkillMarkdown(form),
		files: form.files,
		revision,
	};
}

/**
 * Where an uploaded file lands, following the Agent Skills folder
 * convention: executables under scripts/, other text under references/,
 * binaries under assets/.
 */
export function defaultUploadPath(
	filename: string,
	encoding: SkillFile["encoding"],
): string {
	if (encoding === "base64") return `assets/${filename}`;
	return /\.(py|sh|bash|js|mjs|ts|rb|pl|ps1)$/i.test(filename)
		? `scripts/${filename}`
		: `references/${filename}`;
}

/** Read a browser File into a SkillFile, falling back to base64 for binaries. */
export async function readUploadedFile(file: File): Promise<SkillFile> {
	const bytes = new Uint8Array(await file.arrayBuffer());
	try {
		const content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		return {
			path: defaultUploadPath(file.name, "utf-8"),
			content,
			encoding: "utf-8",
		};
	} catch {
		let binary = "";
		for (const byte of bytes) binary += String.fromCharCode(byte);
		return {
			path: defaultUploadPath(file.name, "base64"),
			content: btoa(binary),
			encoding: "base64",
		};
	}
}

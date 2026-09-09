/**
 * The SKILL.md document is the editor's single source of truth — what the
 * API stores and the model reads. These helpers let the editor offer a form
 * (name, description, body) over that document without a YAML library: the
 * two required keys are split out of the frontmatter, every other line of it
 * is carried through verbatim, and a document whose frontmatter cannot be
 * round-tripped safely (folded scalars, nested mappings…) is edited raw.
 */

import type { SkillFile } from "@/types/skills";
import {
	SKILL_DESCRIPTION_MAX,
	SKILL_NAME_MAX,
	SKILL_NAME_PATTERN,
} from "@/types/skills";

export interface SkillFields {
	name: string;
	description: string;
	/** Frontmatter lines other than `name:` / `description:`, verbatim. */
	extra: string[];
	/** The markdown after the frontmatter. */
	body: string;
}

const FRONTMATTER = /^---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)([\s\S]*)$/;
// `key: value` on one line. Anything else (a folded `>` / `|` scalar, a
// nested mapping, a list) means the document is not ours to rewrite.
const SIMPLE_LINE = /^([A-Za-z0-9_-]+):[ \t]*(.*)$/;

/**
 * Split a SKILL.md into editable fields, or `null` when its frontmatter is
 * not a flat list of `key: value` lines — the editor then edits it raw.
 */
export function splitSkillMarkdown(content: string): SkillFields | null {
	const match = FRONTMATTER.exec(content.replace(/\r\n/g, "\n"));
	if (!match) return null;
	const fields: SkillFields = { name: "", description: "", extra: [], body: match[2] };
	for (const line of match[1].split("\n")) {
		if (!line.trim() || line.trimStart().startsWith("#")) {
			fields.extra.push(line);
			continue;
		}
		const pair = SIMPLE_LINE.exec(line);
		if (!pair) return null;
		const [, key, raw] = pair;
		const value = unquote(raw.trim());
		if (value === null) return null;
		if (key === "name") fields.name = value;
		else if (key === "description") fields.description = value;
		else fields.extra.push(line);
	}
	return fields;
}

/** Rebuild the document; the inverse of `splitSkillMarkdown`. */
export function composeSkillMarkdown(fields: SkillFields): string {
	const lines = [
		`name: ${yamlScalar(fields.name)}`,
		`description: ${yamlScalar(fields.description)}`,
		...fields.extra,
	];
	return `---\n${lines.join("\n")}\n---\n\n${fields.body.replace(/^\n+/, "")}`;
}

/**
 * Quote a value whenever YAML could read it as anything but this string:
 * indicators, a leading/trailing space, an empty value, a `key: value`
 * shape, or a word YAML types (`yes`, `null`, `1.5`…).
 */
export function yamlScalar(value: string): string {
	const plainSafe =
		value !== "" &&
		!/^[\s\-?:,[\]{}#&*!|>'"%@`]/.test(value) &&
		!/\s$/.test(value) &&
		!/:\s|\s#/.test(value) &&
		!/^(?:true|false|yes|no|on|off|null|~|[-+]?(?:\d[\d_]*)?\.?\d+(?:e[-+]?\d+)?|0x[0-9a-f]+|[-+]?\.(?:inf|nan))$/i.test(
			value,
		);
	if (plainSafe) return value;
	return `"${value.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`;
}

/**
 * The string a simple `key: value` line holds: plain, or double/single
 * quoted with the quotes removed. `null` when the value uses a YAML feature
 * this parser does not handle (folded scalars, flow collections, anchors…).
 */
function unquote(raw: string): string | null {
	if (raw === "") return "";
	if (raw.startsWith('"')) {
		if (!raw.endsWith('"') || raw.length < 2) return null;
		try {
			return JSON.parse(raw) as string;
		} catch {
			return null;
		}
	}
	if (raw.startsWith("'")) {
		if (!raw.endsWith("'") || raw.length < 2) return null;
		return raw.slice(1, -1).replace(/''/g, "'");
	}
	if (/^[>|[{&*!]/.test(raw)) return null;
	// A trailing comment is dropped by YAML too; keep the value only.
	return raw.replace(/\s+#.*$/, "");
}

export function skillNameError(name: string): string | null {
	if (!name) return "A name is required";
	if (name.length > SKILL_NAME_MAX) return `At most ${SKILL_NAME_MAX} characters`;
	if (!SKILL_NAME_PATTERN.test(name)) {
		return "Lowercase letters, digits and single hyphens only (e.g. web-research)";
	}
	return null;
}

export function skillDescriptionError(description: string): string | null {
	if (!description.trim()) return "A description is required";
	if (description.length > SKILL_DESCRIPTION_MAX) {
		return `At most ${SKILL_DESCRIPTION_MAX} characters`;
	}
	return null;
}

/** Where an uploaded file lands by convention: scripts, references or assets. */
export function defaultFolder(filename: string, binary: boolean): string {
	if (binary) return "assets";
	const extension = filename.split(".").pop()?.toLowerCase() ?? "";
	if (["py", "sh", "js", "ts", "rb", "sql", "r", "bash", "zsh"].includes(extension)) {
		return "scripts";
	}
	return "references";
}

/** Read a browser `File` into a `SkillFile`: text when it decodes as UTF-8, else base64. */
export async function readSkillFile(file: File): Promise<SkillFile> {
	const bytes = new Uint8Array(await file.arrayBuffer());
	try {
		const content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
		return {
			path: `${defaultFolder(file.name, false)}/${file.name}`,
			content,
			encoding: "utf-8",
		};
	} catch {
		let binary = "";
		for (const byte of bytes) binary += String.fromCharCode(byte);
		return {
			path: `${defaultFolder(file.name, true)}/${file.name}`,
			content: btoa(binary),
			encoding: "base64",
		};
	}
}

/** Byte size of a file's content, for the panel's placeholder. */
export function skillFileSize(file: SkillFile): number {
	if (file.encoding === "base64") {
		const padding = (file.content.match(/=+$/) ?? [""])[0].length;
		return Math.floor((file.content.length * 3) / 4) - padding;
	}
	return new TextEncoder().encode(file.content).length;
}

export function formatBytes(size: number): string {
	if (size < 1024) return `${size} B`;
	if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
	return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

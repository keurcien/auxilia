import { describe, expect, it } from "vitest";
import {
	composeSkillMarkdown,
	skillNameError,
	splitSkillMarkdown,
	yamlScalar,
} from "./skill-form";

describe("splitSkillMarkdown", () => {
	it("splits the two required keys out and keeps the rest verbatim", () => {
		const fields = splitSkillMarkdown(
			"---\nname: web-research\ndescription: Research a topic\nlicense: MIT\n# a comment\nallowed-tools: read_file\n---\n\n# Steps\n\nDo it.\n",
		);
		expect(fields).toEqual({
			name: "web-research",
			description: "Research a topic",
			extra: ["license: MIT", "# a comment", "allowed-tools: read_file"],
			body: "# Steps\n\nDo it.\n",
		});
	});

	it("treats the blank line after the closing --- as the separator", () => {
		// It is what `composeSkillMarkdown` writes, so leaving it on the body
		// put an undeletable blank line at the top of the editor: removing it
		// composed a byte-identical document and the split handed it back.
		const doc = composeSkillMarkdown({
			name: "deploy",
			description: "Ship it",
			extra: [],
			body: "# When to use\n",
		});
		const fields = splitSkillMarkdown(doc);

		expect(fields?.body).toBe("# When to use\n");
		expect(composeSkillMarkdown(fields!)).toBe(doc);
	});

	it("keeps a blank line the author actually wrote", () => {
		const fields = splitSkillMarkdown("---\nname: a\ndescription: b\n---\n\n\n# Steps\n");
		expect(fields?.body).toBe("\n# Steps\n");
	});

	it("unquotes double and single quoted values", () => {
		const fields = splitSkillMarkdown(
			`---\nname: "quoted"\ndescription: 'It''s: tricky'\n---\nbody`,
		);
		expect(fields?.name).toBe("quoted");
		expect(fields?.description).toBe("It's: tricky");
	});

	it("refuses documents it could not rewrite safely", () => {
		expect(splitSkillMarkdown("no frontmatter")).toBeNull();
		expect(splitSkillMarkdown("---\nname: a\ndescription: >\n  folded\n---\nbody")).toBeNull();
		// A nested block is fine — it is carried through verbatim (see below).
		expect(splitSkillMarkdown("---\nname: a\nmetadata:\n  author: me\n---\nbody")).not.toBeNull();
		expect(splitSkillMarkdown("---\nname: a\ntags: [a, b]\n---\nbody")).toBeNull();
	});
});

describe("composeSkillMarkdown", () => {
	it("round-trips what splitSkillMarkdown produced", () => {
		const content = "---\nname: report\ndescription: Write a report\nlicense: MIT\n---\n\nBody here.\n";
		const fields = splitSkillMarkdown(content);
		expect(fields).not.toBeNull();
		expect(composeSkillMarkdown(fields!)).toBe(content);
	});

	it("quotes what YAML would misread", () => {
		expect(yamlScalar("plain words")).toBe("plain words");
		expect(yamlScalar("Do this: then that")).toBe('"Do this: then that"');
		expect(yamlScalar("yes")).toBe('"yes"');
		expect(yamlScalar("1.5")).toBe('"1.5"');
		expect(yamlScalar("")).toBe('""');
		expect(yamlScalar("#tag")).toBe('"#tag"');
		// A quote inside a plain scalar is just a character.
		expect(yamlScalar('say "hi"')).toBe('say "hi"');
		expect(yamlScalar('"quoted"')).toBe('"\\"quoted\\""');
		const composed = composeSkillMarkdown({
			name: "x",
			description: "a: b",
			extra: [],
			body: "body",
		});
		expect(splitSkillMarkdown(composed)?.description).toBe("a: b");
	});
});

describe("skillNameError", () => {
	it("mirrors the backend rule", () => {
		expect(skillNameError("web-research")).toBeNull();
		expect(skillNameError("")).toMatch(/required/);
		expect(skillNameError("Web Research")).toMatch(/Lowercase/);
		expect(skillNameError("a--b")).toMatch(/Lowercase/);
		expect(skillNameError("a".repeat(65))).toMatch(/64/);
	});
});

describe("splitSkillMarkdown with nested frontmatter", () => {
	it("carries a nested block through verbatim and round-trips it", () => {
		const doc =
			"---\nname: weekly-brief\ndescription: Format the recap\nlicense: MIT\nmetadata:\n  author: keurcien\n  version: \"1.0\"\n---\n\n# Steps\n";
		const fields = splitSkillMarkdown(doc);
		expect(fields).not.toBeNull();
		expect(fields!.extra).toEqual(["license: MIT", "metadata:", "  author: keurcien", '  version: "1.0"']);
		expect(composeSkillMarkdown({ ...fields!, description: "Format the Monday recap" })).toBe(
			"---\nname: weekly-brief\ndescription: Format the Monday recap\nlicense: MIT\nmetadata:\n  author: keurcien\n  version: \"1.0\"\n---\n\n# Steps\n",
		);
	});

	it("still refuses YAML it cannot round-trip", () => {
		expect(splitSkillMarkdown("---\nname: a\ndescription: >\n  folded\n---\nbody")).toBeNull();
	});
});

describe("script detection", () => {
	it("counts only files under scripts/ as scripts", async () => {
		const { countScripts, isScriptPath } = await import("@/types/skills");
		expect(isScriptPath("scripts/run.py")).toBe(true);
		expect(isScriptPath("scripts/lib/util.py")).toBe(true);
		expect(isScriptPath("scripts/")).toBe(false);
		expect(isScriptPath("scripts.md")).toBe(false);
		expect(isScriptPath("references/scripts/notes.md")).toBe(false);
		expect(
			countScripts([
				{ path: "scripts/a.py" },
				{ path: "references/b.md" },
				{ path: "scripts/c.sh" },
			]),
		).toBe(2);
	});
});

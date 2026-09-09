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
			body: "\n# Steps\n\nDo it.\n",
		});
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
		expect(splitSkillMarkdown("---\nname: a\nmetadata:\n  author: me\n---\nbody")).toBeNull();
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

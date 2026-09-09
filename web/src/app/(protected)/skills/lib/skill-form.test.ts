import { describe, expect, it } from "vitest";
import {
	composeSkillMarkdown,
	defaultUploadPath,
	isValidSkillName,
	yamlScalar,
} from "./skill-form";

describe("yamlScalar", () => {
	it("keeps tame prose plain", () => {
		expect(yamlScalar("Use when greeting a new customer.")).toBe(
			"Use when greeting a new customer.",
		);
	});
	it("quotes YAML punctuation, reserved words and numbers", () => {
		expect(yamlScalar("Step 1: greet")).toBe('"Step 1: greet"');
		expect(yamlScalar("a # comment")).toBe('"a # comment"');
		expect(yamlScalar("yes")).toBe('"yes"');
		expect(yamlScalar("2024")).toBe('"2024"');
		expect(yamlScalar("- item")).toBe('"- item"');
		expect(yamlScalar("trailing ")).toBe('"trailing "');
		expect(yamlScalar('say "hi"')).toBe('"say \\"hi\\""');
	});
});

describe("composeSkillMarkdown", () => {
	it("emits frontmatter followed by the trimmed body", () => {
		expect(
			composeSkillMarkdown({
				name: "greeting",
				description: "Use when greeting a new customer.",
				instructions: "\nGreet the customer warmly.\n\n",
				files: [],
			}),
		).toBe(
			"---\nname: greeting\ndescription: Use when greeting a new customer.\n---\n\nGreet the customer warmly.\n",
		);
	});
});

describe("isValidSkillName", () => {
	it("accepts kebab-case and rejects everything else", () => {
		expect(isValidSkillName("pdf-tools")).toBe(true);
		expect(isValidSkillName("a1")).toBe(true);
		expect(isValidSkillName("PDF")).toBe(false);
		expect(isValidSkillName("-x")).toBe(false);
		expect(isValidSkillName("a--b")).toBe(false);
		expect(isValidSkillName("with space")).toBe(false);
		expect(isValidSkillName("")).toBe(false);
	});
});

describe("defaultUploadPath", () => {
	it("routes by kind", () => {
		expect(defaultUploadPath("check.py", "utf-8")).toBe("scripts/check.py");
		expect(defaultUploadPath("notes.md", "utf-8")).toBe("references/notes.md");
		expect(defaultUploadPath("logo.png", "base64")).toBe("assets/logo.png");
	});
});

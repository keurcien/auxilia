import { describe, expect, it } from "vitest";
import { isDetached, isSourced, repoLabel, shortRevision } from "./skills";

describe("provenance", () => {
	// `sourceRevision` is the pin and `sourceId` the live link — the three
	// states are read off those two fields, never a state column.
	const skill = (sourceRevision: string | null, sourceId: string | null) => ({
		sourceRevision,
		sourceId,
	});

	it("reads written-here, synced and detached off the two fields", () => {
		expect(isSourced(skill(null, null))).toBe(false);
		expect(isDetached(skill(null, null))).toBe(false);

		expect(isSourced(skill("abc123", "src-1"))).toBe(true);
		expect(isDetached(skill("abc123", "src-1"))).toBe(false);

		expect(isSourced(skill("abc123", null))).toBe(true);
		expect(isDetached(skill("abc123", null))).toBe(true);
	});
});

describe("repoLabel", () => {
	it("keeps the whole path so nested groups stay distinguishable", () => {
		// Two different GitLab repositories that share a trailing pair. The
		// detached-skill UI names the repository to reconnect, so collapsing
		// these to `team/tools` would point at the wrong one.
		expect(repoLabel("https://gitlab.com/group/team/tools")).toBe("group/team/tools");
		expect(repoLabel("https://gitlab.com/other/team/tools")).toBe("other/team/tools");
	});

	it("drops the scheme, the host, a trailing slash and .git", () => {
		expect(repoLabel("https://github.com/acme/skills")).toBe("acme/skills");
		expect(repoLabel("https://github.com/acme/skills/")).toBe("acme/skills");
		expect(repoLabel("https://github.com/acme/skills.git")).toBe("acme/skills");
		expect(repoLabel("https://git.internal.example.com/acme/skills")).toBe("acme/skills");
	});

	it("is empty for a missing URL, so callers can fall back with ||", () => {
		expect(repoLabel(null)).toBe("");
		expect(repoLabel(undefined)).toBe("");
		expect(repoLabel("")).toBe("");
	});
});

describe("shortRevision", () => {
	it("shortens a SHA and leaves a tag alone", () => {
		expect(shortRevision("0123456789abcdef0123")).toBe("0123456");
		expect(shortRevision("v1.2.3")).toBe("v1.2.3");
		expect(shortRevision(null)).toBe("");
	});
});

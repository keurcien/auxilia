import type { BoundAgent } from "./agents";

export type SkillFileEncoding = "utf-8" | "base64";

/** A supporting file of a skill, relative to the skill folder. */
export interface SkillFile {
	path: string;
	content: string;
	encoding: SkillFileEncoding;
}

export type SkillSourceKind = "github" | "gitlab";

/**
 * A library row — `GET /skills` never carries the document or its files.
 *
 * `scriptCount` is how many files sit under `scripts/`: zero means the skill
 * runs on any agent, more means its scripts only run on an agent with code
 * execution (the instructions still apply everywhere). `agentCount` is how
 * many agents have it enabled — a skill in use can't be deleted or renamed.
 */
export interface SkillSummary {
	id: string;
	ownerId: string;
	name: string;
	description: string;
	revision: number;
	fileCount: number;
	scriptCount: number;
	agentCount: number;
	/** The same agents `agentCount` counts — the library's avatar stack. */
	agents: BoundAgent[];
	updatedAt: string;
	/** May change the content — never for a skill that came from a repository. */
	canEdit: boolean;
	/** May delete or adopt — the owner or a workspace admin. */
	canManage: boolean;
	/** The repository this skill is pinned to; null once it is disconnected. */
	sourceId: string | null;
	sourceName: string | null;
	/** Which host, so the library can show its mark. Null unless connected. */
	sourceKind: SkillSourceKind | null;
	/**
	 * The repository the content came from. Unlike `sourceId` it outlives the
	 * disconnect, so it is what names the repository of a detached skill — and
	 * what a reconnect matches on, so only the repository that left a skill
	 * behind can claim it back.
	 */
	sourceUrl: string | null;
	sourcePath: string | null;
	/**
	 * The commit the content was read at — the pin, and so what says this
	 * skill came from a repository at all. Null for one written here.
	 */
	sourceRevision: string | null;
	/** Content hash. Every skill has one, a skill written here included. */
	digest: string | null;
	/** A newer synced version is waiting to be adopted. */
	updateAvailable: boolean;
	/** The last sync no longer found this skill in its repository. */
	missingUpstream: boolean;
}

/** A newer version of a sourced skill, waiting to be adopted. */
export interface SkillVersionInfo {
	digest: string;
	revision: string;
	discoveredAt: string;
}

/** The full skill — `GET /skills/{id}` and every save result. */
export interface Skill extends SkillSummary {
	/** The whole SKILL.md, frontmatter included. */
	content: string;
	files: SkillFile[];
	available: SkillVersionInfo | null;
}

/** One skillkit validation finding, as the API reports it. */
export interface SkillIssue {
	code: string;
	severity: "error" | "warning";
	message: string;
	path: string | null;
	suggestion: string | null;
}

export interface SkillFileChange {
	path: string;
	status: "added" | "removed" | "modified";
	oldSize: number | null;
	newSize: number | null;
	binary: boolean;
	unified: string | null;
}

/** What adopting the newest synced version would change. */
export interface SkillDiff {
	name: string;
	status: "changed" | "unchanged";
	oldDigest: string;
	newDigest: string;
	oldRevision: string | null;
	newRevision: string | null;
	categories: string[];
	descriptionChanged: boolean;
	instructionsChanged: boolean;
	scriptsChanged: boolean;
	requirementsChanged: boolean;
	files: SkillFileChange[];
}

// -- sources -------------------------------------------------------------------

/** ok · auth (token missing/refused) · not_found · empty (no commits) · unavailable · invalid; null = never synced. */
export type SkillSourceStatus =
	| "ok"
	| "auth"
	| "not_found"
	| "empty"
	| "unavailable"
	| "invalid";

/**
 * What the last sync did to one skill — every decision, not only the
 * failures. The plan answers "what will this do?" before the button; this is
 * the only answer to "what did it do?" once the dialog is gone.
 */
export interface SkillSourceReportEntry {
	path: string;
	name: string;
	status: SkillSyncStatus;
	issues: SkillIssue[];
}

/**
 * What a sync would do to one skill.
 *
 * `unchanged` and `updated` both leave the live skill alone — a sync only
 * makes a new version available, and adopting it stays a separate per-skill
 * decision. `new` is the one status that changes the library on the spot;
 * `gone` only flags a skill, which keeps working at its pinned version.
 */
export type SkillSyncStatus = "new" | "updated" | "unchanged" | "gone" | "skipped";

export interface SkillSyncEntry {
	name: string;
	path: string;
	status: SkillSyncStatus;
	scriptCount: number;
	issues: SkillIssue[];
}

/** What a sync would do, computed without writing anything. */
export interface SkillSyncPlan {
	revision: string;
	currentRevision: string | null;
	entries: SkillSyncEntry[];
}

export interface SkillSource {
	id: string;
	ownerId: string;
	name: string;
	kind: SkillSourceKind;
	url: string;
	ref: string;
	subpath: string | null;
	hasToken: boolean;
	lastRevision: string | null;
	lastSyncedAt: string | null;
	lastStatus: SkillSourceStatus | null;
	lastError: string | null;
	lastReport: SkillSourceReportEntry[];
	skillCount: number;
	canManage: boolean;
	createdAt: string | null;
	updatedAt: string;
}

export interface SkillSourceCreate {
	url: string;
	kind?: SkillSourceKind | null;
	ref: string;
	subpath?: string | null;
	token?: string | null;
}

export interface SkillSourcePreviewSkill {
	name: string;
	description: string;
	path: string;
	container: string;
	scriptCount: number;
	ok: boolean;
	issues: SkillIssue[];
}

export interface SkillSourcePreview {
	kind: SkillSourceKind;
	name: string;
	revision: string;
	skills: SkillSourcePreviewSkill[];
	issues: SkillIssue[];
}

/** Seven characters of a commit SHA, or the whole thing when it is short. */
/**
 * Where a skill's content comes from, read off the two provenance fields —
 * there is no third field, and so no state the API has to keep in step.
 *
 * `sourceRevision` is the pin: only a sync or an adopt writes it, so it marks
 * the content as a repository's whatever happens to the repository later.
 * `sourceId` is the live link. Neither → written here. Both → pinned and
 * connected. Pin without link → detached: the document, files and scripts
 * stay in the row and still run, and the content is frozen until the
 * repository is connected again — the library can still drop the skill,
 * which is not the same as editing it.
 */
export const isSourced = (skill: Pick<SkillSummary, "sourceRevision">): boolean =>
	skill.sourceRevision !== null;

export const isDetached = (skill: Pick<SkillSummary, "sourceRevision" | "sourceId">): boolean =>
	isSourced(skill) && skill.sourceId === null;

export const shortRevision = (revision: string | null | undefined): string =>
	revision ? (revision.length > 12 ? revision.slice(0, 7) : revision) : "";

/**
 * `owner/repo` from a repository URL — what a detached skill has instead of a
 * `sourceName`, since the row that carried the name is gone. The whole URL is
 * kept as the title, so nothing is hidden, only shortened.
 */
export const repoLabel = (url: string | null | undefined): string => {
	if (!url) return "";
	const path = url.replace(/^https?:\/\//, "").replace(/\.git$/, "").replace(/\/+$/, "");
	const parts = path.split("/");
	return parts.length > 2 ? parts.slice(-2).join("/") : path;
};

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
	scriptCount: number;
}

/**
 * Same rule as the backend (`app/skills/schemas.py`) and the Agent Skills
 * spec: lowercase alphanumerics in hyphen-separated words.
 *
 * Written as one flat character class plus explicit edge checks rather than
 * `[a-z0-9]+(?:-[a-z0-9]+)*`. The nested quantifier in that form is what
 * ReDoS detectors flag; it is in fact linear, because the inner class cannot
 * match `-`, but a shape no tool has to reason about is worth more than the
 * argument.
 */
const SKILL_NAME_CHARS = /^[a-z0-9-]+$/;

export function isValidSkillName(name: string): boolean {
	return (
		SKILL_NAME_CHARS.test(name) &&
		!name.startsWith("-") &&
		!name.endsWith("-") &&
		!name.includes("--")
	);
}
export const SKILL_NAME_MAX = 64;
export const SKILL_DESCRIPTION_MAX = 1024;

/** The Agent Skills folder whose files are programs — same rule as the backend. */
export const SKILL_SCRIPTS_DIR = "scripts";

export const isScriptPath = (path: string): boolean =>
	path.startsWith(`${SKILL_SCRIPTS_DIR}/`) && path.length > SKILL_SCRIPTS_DIR.length + 1;

export const countScripts = (files: readonly Pick<SkillFile, "path">[]): number =>
	files.filter((file) => isScriptPath(file.path)).length;

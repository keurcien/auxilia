import type { BoundAgent } from "./agents";

export type SkillFileEncoding = "utf-8" | "base64";

/** A supporting file of a skill, relative to the skill folder. */
export interface SkillFile {
	path: string;
	content: string;
	encoding: SkillFileEncoding;
}

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
	updatedAt: string;
	/** May change the content — never for a skill synced from a repository. */
	canEdit: boolean;
	/** May delete or adopt — the owner or a workspace admin. */
	canManage: boolean;
	/** Provenance: null = written in the app, live on the next run. */
	sourceId: string | null;
	sourceName: string | null;
	sourcePath: string | null;
	/** The commit the pinned content came from (sourced skills). */
	sourceRevision: string | null;
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
	/** The agents this skill is enabled on, by name. */
	agents: BoundAgent[];
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

export type SkillSourceKind = "github" | "gitlab";

/** ok · auth (token missing/refused) · not_found · unavailable · invalid; null = never synced. */
export type SkillSourceStatus = "ok" | "auth" | "not_found" | "unavailable" | "invalid";

export interface SkillSourceReportEntry {
	path: string;
	name: string;
	issues: SkillIssue[];
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
export const shortRevision = (revision: string | null | undefined): string =>
	revision ? (revision.length > 12 ? revision.slice(0, 7) : revision) : "";

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

/** Same rule as the backend (`app/skills/schemas.py`) and the Agent Skills spec. */
export const SKILL_NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const SKILL_NAME_MAX = 64;
export const SKILL_DESCRIPTION_MAX = 1024;

/** The Agent Skills folder whose files are programs — same rule as the backend. */
export const SKILL_SCRIPTS_DIR = "scripts";

export const isScriptPath = (path: string): boolean =>
	path.startsWith(`${SKILL_SCRIPTS_DIR}/`) && path.length > SKILL_SCRIPTS_DIR.length + 1;

export const countScripts = (files: readonly Pick<SkillFile, "path">[]): number =>
	files.filter((file) => isScriptPath(file.path)).length;

import type { ResourceVisibility } from "@/types/visibility";

export type ScopeResourceKind =
	| "agent"
	| "project"
	| "trigger"
	| "mcp_server"
	| "skill";

/** `target` is the requested change, `required` is needed for it to be
 * accepted, `suggested` shares what already relies on the target with it. */
export type ScopeChangeRole = "target" | "required" | "suggested";

export interface ScopeChange {
	kind: ScopeResourceKind;
	id: string;
	visibility: ResourceVisibility;
	teamIds: string[];
}

export interface ScopePlanItem {
	kind: ScopeResourceKind;
	id: string;
	name: string;
	role: ScopeChangeRole;
	depth: number;
	reason: string | null;
	canManage: boolean;
	currentVisibility: ResourceVisibility;
	currentTeamIds: string[];
	visibility: ResourceVisibility;
	teamIds: string[];
}

export interface ScopePlan {
	items: ScopePlanItem[];
	blockers: string[];
	note: string | null;
	/** The target plus every required change. */
	minimal: ScopeChange[];
	/** `minimal` plus the suggestions; null when there is nothing to suggest. */
	complete: ScopeChange[] | null;
}

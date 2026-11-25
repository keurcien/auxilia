import type { ResourceVisibility } from "@/types/visibility";

export interface Audience {
	visibility: ResourceVisibility;
	ownerId?: string | null;
	teamIds?: string[];
}

/** Mirrors the backend `audience_contains`: can everyone who uses `parent` also use `child`? */
export function audienceContains(parent: Audience, child: Audience): boolean {
	if (parent.visibility === "workspace") return child.visibility === "workspace";
	if (parent.visibility === "teams") {
		if (child.visibility === "workspace") return true;
		const childTeams = new Set(child.teamIds ?? []);
		return (
			child.visibility === "teams" &&
			(parent.teamIds ?? []).every((teamId) => childTeams.has(teamId))
		);
	}
	if (child.visibility === "workspace") return true;
	return parent.ownerId === child.ownerId;
}

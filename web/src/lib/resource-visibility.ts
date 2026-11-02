import type { ResourceVisibility } from "@/types/visibility";

export interface ResourceAudience {
	visibility: ResourceVisibility;
	ownerId: string;
	teamIds: string[];
}

export function audienceContains(
	parent: ResourceAudience,
	child: ResourceAudience,
): boolean {
	if (parent.visibility === "workspace") {
		return child.visibility === "workspace";
	}
	if (parent.visibility === "teams") {
		if (child.visibility === "workspace") return true;
		if (child.visibility !== "teams") return false;
		const childTeams = new Set(child.teamIds);
		return parent.teamIds.every((teamId) => childTeams.has(teamId));
	}
	if (child.visibility === "workspace") return true;
	if (child.visibility === "teams") return false;
	return parent.ownerId === child.ownerId;
}

export function incompatibleSkillReason(
	project: ResourceAudience,
	skill: ResourceAudience,
): string {
	if (skill.visibility === "personal") {
		return "This skill is private to an owner outside the project audience.";
	}
	if (project.visibility === "workspace") {
		return "This skill is not visible to the whole workspace.";
	}
	if (project.visibility === "teams") {
		return "This skill is not visible to every team that can access the project.";
	}
	return "This skill is private to a different owner.";
}

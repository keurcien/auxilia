import type { ResourceVisibility } from "@/types/visibility";

export type ResourceScopeFilter = "all" | ResourceVisibility;

export interface FilterableResource {
	visibility?: ResourceVisibility;
	teamIds?: string[];
}

export function matchesResourceScope(
	resource: FilterableResource,
	scope: ResourceScopeFilter,
	teamIds: string[],
): boolean {
	if (scope === "all") return true;
	if ((resource.visibility ?? "workspace") !== scope) return false;
	if (scope !== "teams" || teamIds.length === 0) return true;
	return resource.teamIds?.some((teamId) => teamIds.includes(teamId)) ?? false;
}

export type ResourceVisibility = "personal" | "workspace" | "teams";

export interface VisibilityFields {
	visibility: ResourceVisibility;
	teamIds: string[];
}

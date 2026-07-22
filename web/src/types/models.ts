export interface Model {
	id: string;
	name: string;
	chef: string;
	chefSlug: string;
	providers: string[];
	// The effective workspace default (admin-flagged model when available,
	// else the first available one) — pickers preselect this row.
	isDefault: boolean;
}

// One row of the admin Settings view (GET /model-providers/models/manage):
// a whitelist model with its enablement state, or an orphan enablement row
// whose model left the whitelist (deprecated).
export interface ManagedModel {
	provider: string;
	modelId: string;
	displayName: string;
	chef: string;
	chefSlug: string;
	multimodal: boolean;
	supportsStructuredOutput: boolean;
	isEnabled: boolean;
	// The explicit admin choice only (no fallback) — unset shows as unset.
	isDefault: boolean;
	deprecated: boolean;
}

export interface WhitelistSyncResult {
	added: string[];
	removed: string[];
	modelCount: number;
	fetchedAt: string;
}

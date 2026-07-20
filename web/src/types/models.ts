export interface Model {
	id: string;
	name: string;
	chef: string;
	chefSlug: string;
	providers: string[];
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
	deprecated: boolean;
}

export interface WhitelistSyncResult {
	added: string[];
	removed: string[];
	modelCount: number;
	fetchedAt: string;
}

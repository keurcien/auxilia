export interface Model {
	id: string;
	name: string;
	chef: string;
	chefSlug: string;
	providers: string[];
	// The effective workspace default (admin-flagged model when available,
	// else the first available one) — pickers preselect this row.
	isDefault: boolean;
	// Whether the model accepts non-text input — gates composer attachments
	// per model (not per chef: GLM 5.3 Flash takes images, plain 5.3 doesn't).
	multimodal: boolean;
	// Maximum input tokens, null when the catalog doesn't know it.
	contextWindow: number | null;
	// Reasoning-effort values the user may pick for this model (empty = no
	// effort knob, render no picker) and the level in effect when they pick
	// nothing (null = provider-managed/dynamic, shown as Auto).
	reasoningEffortLevels: string[];
	reasoningEffortDefault: string | null;
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
	supportsTools: boolean;
	isAvailable: boolean;
	isEnabled: boolean;
	// The explicit admin choice only (no fallback) — unset shows as unset.
	isDefault: boolean;
	// The workspace quick model (explicit choice): used for the runtime's
	// short intermediate calls such as lazy tool-discovery routing.
	isQuick: boolean;
	deprecated: boolean;
}

export type ModelProviderCredentialSource =
	| "database"
	| "environment"
	| "adc"
	| "none";

export interface ModelProviderConfig {
	name: string;
	isConfigured: boolean;
	source: ModelProviderCredentialSource;
	configurationType: "api_key" | "base_url";
	baseUrl: string | null;
	last4: string | null;
	keyLength: number | null;
}

export interface OllamaDiscoveryResult {
	config: ModelProviderConfig;
	discoveredCount: number;
	availableCount: number;
}

export interface WhitelistSyncResult {
	added: string[];
	removed: string[];
	modelCount: number;
	fetchedAt: string;
}

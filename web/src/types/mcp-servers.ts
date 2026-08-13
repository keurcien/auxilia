export type MCPAuthType = "none" | "api_key" | "oauth2";

export interface MCPServer {
	id: string;
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	description?: string;
	createdAt: string;
	updatedAt: string;
	// Static OAuth client_id when configured (not a secret); absent for DCR.
	oauthClientId?: string | null;
}

export interface MCPServerCreate {
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	description?: string;
	apiKey?: string;
	// OAuth credentials for pre-registered OAuth clients
	oauthClientId?: string;
	oauthClientSecret?: string;
}

export interface MCPServerUpdate {
	name?: string;
	url?: string;
	authType?: MCPAuthType;
	// null clears the stored value; undefined leaves it untouched.
	iconUrl?: string | null;
	description?: string | null;
	// Credentials — send only when changing them; blank keeps the stored value.
	apiKey?: string;
	oauthClientId?: string;
	oauthClientSecret?: string;
}

export interface OAuthSecretHint {
	isSet: boolean;
	last4?: string | null;
	length?: number | null;
}

export interface ConnectionTestResult {
	reachable: boolean;
	toolCount?: number | null;
	toolNames?: string[] | null;
	oauthRequired: boolean;
	authUrl?: string | null;
	error?: string | null;
}

export interface OfficialMCPServer extends MCPServer {
	isInstalled: boolean;
	supportsDcr: boolean | null;
}

/** A user's stored OAuth connection to a server (admin view). `expired`
 * means the token is past expiry with no refresh token to renew it. */
export interface MCPServerConnection {
	userId: string;
	name?: string | null;
	email?: string | null;
	status: "active" | "expired";
}

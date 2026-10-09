import type { ResourceVisibility } from "./visibility";

export type MCPAuthType = "none" | "api_key" | "oauth2" | "service_identity";
export type ServiceCredentialProvider =
	| "google_service_account"
	| "custom_http_headers";

export interface MCPServer {
	id: string;
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	imageRevision?: string | null;
	description?: string;
	group?: string | null;
	ownerId?: string;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	disabledTools?: string[];
	createdAt: string;
	updatedAt: string;
	// Static OAuth client_id when configured (not a secret); absent for DCR.
	oauthClientId?: string | null;
	serviceCredentialProvider?: ServiceCredentialProvider | null;
	serviceCredentialPrincipal?: string | null;
	serviceCredentialScopes?: string[];
}

export interface MCPServerCreate {
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	description?: string;
	group?: string | null;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	apiKey?: string;
	// OAuth credentials for pre-registered OAuth clients
	oauthClientId?: string;
	oauthClientSecret?: string;
	serviceCredentialProvider?: ServiceCredentialProvider;
	serviceCredentialsJson?: string;
	serviceCredentialScopes?: string[];
}

export interface MCPServerUpdate {
	name?: string;
	url?: string;
	authType?: MCPAuthType;
	// null clears the stored value; undefined leaves it untouched.
	iconUrl?: string | null;
	description?: string | null;
	group?: string | null;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	// Credentials — send only when changing them; blank keeps the stored value.
	apiKey?: string;
	oauthClientId?: string;
	oauthClientSecret?: string;
	serviceCredentialProvider?: ServiceCredentialProvider;
	serviceCredentialsJson?: string;
	serviceCredentialScopes?: string[];
	disabledTools?: string[];
}

export interface OAuthSecretHint {
	isSet: boolean;
	last4?: string | null;
	length?: number | null;
}

export interface OAuthCallbackInfo {
	callbackUrl: string;
}

export interface MCPServerTool {
	name: string;
	description?: string | null;
}

/**
 * GET /mcp-servers/{id}/list-tools — a discriminated union, always 200.
 *
 * Needing OAuth is an expected answer for a server this user has not connected
 * yet, so it is a variant rather than a 401 the caller has to catch. (It used
 * to be an exception an app-global backend handler turned into a 401.)
 */
export type ListToolsResult =
	| { status: "ok"; tools: MCPServerTool[] }
	| { status: "auth_required"; authUrl: string };

export interface ConnectionTestResult {
	reachable: boolean;
	toolCount?: number | null;
	toolNames?: string[] | null;
	oauthRequired: boolean;
	authUrl?: string | null;
	error?: string | null;
}

// A reusable template in the official catalog (a CDN-hosted file, not a DB
// row). Each installation copies these fields into a new workspace MCPServer.
export interface OfficialMCPServer {
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	description?: string;
	isInstalled: boolean;
	installedCount?: number;
	supportsDcr: boolean | null;
}

/** A user's stored OAuth connection to a server (admin view). `expired`
 * means the token is past expiry with no refresh token to renew it. */
export interface MCPServerConnection {
	userId: string;
	name?: string | null;
	email?: string | null;
	pictureUrl?: string | null;
	imageRevision?: string | null;
	status: "active" | "expired";
}

export interface MCPCatalogSyncResult {
	added: string[];
	removed: string[];
	serverCount: number;
	fetchedAt: string;
}

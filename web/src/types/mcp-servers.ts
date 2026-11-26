import type { ResourceVisibility } from "./visibility";

export type MCPAuthType =
	"none" | "api_key" | "oauth2" | "service_identity" | "custom_http";
/** `personal`: every user authenticates with their own account or secret.
 * `shared`: one credential configured on the server, used by everyone. */
export type MCPCredentialScope = "shared" | "personal";
export type OAuthRedirectMode = "hosted_callback" | "loopback_manual";
export type ServiceCredentialProvider =
	| "google_service_account"
	| "oauth_client_credentials"
	| "github_app"
	| "aws_iam"
	| "azure_managed_identity"
	| "custom_http_headers";

export interface MCPServer {
	id: string;
	name: string;
	url: string;
	authType: MCPAuthType;
	credentialScope?: MCPCredentialScope;
	// Header names each user fills in for a personal custom HTTP server.
	personalHeaderNames?: string[];
	iconUrl?: string;
	imageRevision?: string | null;
	description?: string;
	group?: string | null;
	ownerId?: string;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	disabledTools?: string[];
	managedBy?: string | null;
	managedResourceId?: string | null;
	managedEndpoint?: string | null;
	createdAt: string;
	updatedAt: string;
	// Static OAuth client_id when configured (not a secret); absent for DCR.
	oauthClientId?: string | null;
	serviceCredentialProvider?: ServiceCredentialProvider | null;
	serviceCredentialPrincipal?: string | null;
	serviceCredentialScopes?: string[];
}

export type MCPServerAuthShape = Pick<MCPServer, "authType" | "credentialScope">;

/** Each user enters their own API key or header values (stored per user). */
export function usesUserCredentials(server: MCPServerAuthShape): boolean {
	return (
		server.credentialScope === "personal" &&
		(server.authType === "api_key" || server.authType === "custom_http")
	);
}

/** Each user authenticates with their own account or secret. */
export function isPersonalAuth(server: MCPServerAuthShape): boolean {
	return server.authType === "oauth2" || usesUserCredentials(server);
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
	credentialScope?: MCPCredentialScope;
	personalHeaderNames?: string[];
	// The creator's own secret for a personal server, saved as their connection.
	personalCredentials?: PersonalCredentialsInput;
	apiKey?: string;
	// OAuth credentials for pre-registered OAuth clients
	oauthClientId?: string;
	oauthClientSecret?: string;
	serviceCredentialProvider?: ServiceCredentialProvider;
	serviceCredentialsJson?: string;
	serviceCredentialScopes?: string[];
}

/** One user's own secret for a personal API-key or custom HTTP server. */
export interface PersonalCredentialsInput {
	apiKey?: string;
	headers?: { name: string; value: string }[];
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
	// Credentials: undefined keeps the stored value; explicit null for both
	// OAuth fields removes static credentials and returns the server to DCR.
	apiKey?: string;
	oauthClientId?: string | null;
	oauthClientSecret?: string | null;
	serviceCredentialProvider?: ServiceCredentialProvider;
	serviceCredentialsJson?: string;
	serviceCredentialScopes?: string[];
	// Changing them clears every user's stored header values.
	personalHeaderNames?: string[];
	disabledTools?: string[];
}

/** How the chat gallery downloads an image from an id the server's tools return. */
export interface ImagePreviewSettings {
	urlTemplate: string;
	headerName: string | null;
	headerValueSet: boolean;
}

export interface ImagePreviewSettingsUpdate {
	urlTemplate: string;
	headerName: string | null;
	/** Omitted keeps the stored value while the header name is unchanged. */
	headerValue?: string;
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

export interface MCPToolLoadError {
	status: "error";
	code: string;
	title: string;
	detail: string;
	action?: string | null;
	retryable: boolean;
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
	| {
			status: "auth_required";
			authUrl: string;
			oauthRedirectMode: OAuthRedirectMode;
			oauthSignInUrl?: string | null;
	  }
	// A personal API-key or custom HTTP server this user has no secret for yet.
	| { status: "credentials_required" }
	| MCPToolLoadError;

export interface ConnectionTestResult {
	reachable: boolean;
	toolCount?: number | null;
	toolNames?: string[] | null;
	oauthRequired: boolean;
	credentialsRequired?: boolean;
	authUrl?: string | null;
	oauthRedirectMode: OAuthRedirectMode;
	oauthSignInUrl?: string | null;
	error?: string | null;
}

export interface OAuthManualCallbackResponse {
	success: boolean;
	serverId: string;
	serverName: string;
}

// A reusable template in the official catalog (a CDN-hosted file, not a DB
// row). Each installation copies these fields into a new workspace MCPServer.
export interface MCPServerUrlOption {
	label: string;
	url: string;
	description?: string | null;
}

export interface OfficialMCPServer {
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	description?: string;
	isInstalled: boolean;
	installedCount?: number;
	supportsDcr: boolean | null;
	supportsCimd?: boolean | null;
	requiresUrlConfiguration?: boolean;
	urlOptions?: MCPServerUrlOption[];
	customHttpHeaders?: string[];
	serviceCredentialProviders?: ServiceCredentialProvider[];
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

export interface MCPConnectionReference {
	serverId: string;
	serverName: string;
}

export interface MCPDisconnectedConnection extends MCPConnectionReference {
	providerRevocation: "succeeded" | "unsupported" | "failed";
	warning?: string | null;
}

export interface MCPConnectionDisconnectFailure
	extends MCPConnectionReference {
	detail: string;
}

export interface MCPConnectionDisconnectSummary {
	disconnected: MCPDisconnectedConnection[];
	alreadyAbsent: MCPConnectionReference[];
	failed: MCPConnectionDisconnectFailure[];
	unaffectedShared: MCPConnectionReference[];
}

export interface MCPCatalogSyncResult {
	added: string[];
	removed: string[];
	serverCount: number;
	fetchedAt: string;
}

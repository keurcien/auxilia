import {
	MCPAuthType,
	MCPServerCreate,
	OfficialMCPServer,
} from "@/types/mcp-servers";

export interface MCPServerCreateFormValues {
	name: string;
	url: string;
	description: string;
	authType: MCPAuthType;
	apiKey: string;
	oauthClientId: string;
	oauthClientSecret: string;
	iconUrl: string;
}

export type MCPServerCreateFormErrors = Partial<
	Record<keyof MCPServerCreateFormValues, string>
>;

export function requiresStaticOAuthCredentials(
	officialServer: OfficialMCPServer | null,
): boolean {
	return (
		officialServer?.supportsDcr === false &&
		officialServer.authType === "oauth2"
	);
}

export function validateMCPServerCreateForm(
	form: MCPServerCreateFormValues,
	officialServer: OfficialMCPServer | null,
): MCPServerCreateFormErrors {
	const errors: MCPServerCreateFormErrors = {};
	const oauthClientId = form.oauthClientId.trim();
	const oauthClientSecret = form.oauthClientSecret.trim();

	if (!form.name.trim()) errors.name = "Name is required.";
	if (!form.url.trim()) errors.url = "Server address is required.";

	// The backend rejects api_key servers without a key — catch it inline.
	if (form.authType === "api_key" && !form.apiKey.trim()) {
		errors.apiKey = "API key is required.";
	}

	if (form.authType === "oauth2" && oauthClientSecret && !oauthClientId) {
		errors.oauthClientId =
			"Client ID is required when providing a Client Secret.";
	}
	if (form.authType === "oauth2" && oauthClientId && !oauthClientSecret) {
		errors.oauthClientSecret =
			"Client Secret is required when providing a Client ID.";
	}

	// Only when OAuth is still the selected method — switching the auth type
	// away from a non-DCR catalog entry must not demand OAuth credentials.
	if (
		form.authType === "oauth2" &&
		requiresStaticOAuthCredentials(officialServer)
	) {
		if (!oauthClientId) {
			errors.oauthClientId = "Client ID is required.";
		}
		if (!oauthClientSecret) {
			errors.oauthClientSecret = "Client Secret is required.";
		}
	}

	return errors;
}

export function buildMCPServerCreatePayload(
	form: MCPServerCreateFormValues,
): MCPServerCreate {
	const apiKey = form.authType === "api_key" ? form.apiKey || undefined : undefined;
	const oauthClientId =
		form.authType === "oauth2" ? form.oauthClientId || undefined : undefined;
	const oauthClientSecret =
		form.authType === "oauth2" ? form.oauthClientSecret || undefined : undefined;

	return {
		name: form.name,
		url: form.url,
		authType: form.authType,
		description: form.description || undefined,
		iconUrl: form.iconUrl || undefined,
		apiKey,
		oauthClientId,
		oauthClientSecret,
	};
}

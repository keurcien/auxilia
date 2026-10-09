import {
	MCPAuthType,
	MCPServerCreate,
	OfficialMCPServer,
	ServiceCredentialProvider,
} from "@/types/mcp-servers";
import type { ResourceVisibility } from "@/types/visibility";

export interface MCPServerCreateFormValues {
	name: string;
	url: string;
	description: string;
	group: string;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	authType: MCPAuthType;
	apiKey: string;
	oauthClientId: string;
	oauthClientSecret: string;
	serviceCredentialProvider?: ServiceCredentialProvider;
	serviceCredentialsJson?: string;
	serviceCredentialScopes?: string;
	serviceHeaders?: { name: string; value: string }[];
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
	if (form.visibility === "teams" && (form.teamIds?.length ?? 0) === 0) {
		errors.teamIds = "Select at least one team.";
	}

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
	if (form.authType === "service_identity") {
		if (
			form.serviceCredentialProvider === "google_service_account" &&
			!form.serviceCredentialsJson?.trim()
		) {
			errors.serviceCredentialsJson = "A service credential file is required.";
		}
		if (form.serviceCredentialProvider === "custom_http_headers") {
			const headerError = validateServiceHeaders(form.serviceHeaders);
			if (headerError) errors.serviceHeaders = headerError;
		}
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
	const payload: MCPServerCreate = {
		name: form.name,
		url: form.url,
		authType: form.authType,
		description: form.description || undefined,
		group: form.group || null,
		visibility: form.visibility ?? "workspace",
		teamIds: form.teamIds ?? [],
		iconUrl: form.iconUrl || undefined,
		apiKey,
		oauthClientId,
		oauthClientSecret,
	};
	if (form.authType === "service_identity") {
		payload.serviceCredentialProvider =
			form.serviceCredentialProvider ?? "google_service_account";
		payload.serviceCredentialsJson = buildServiceCredentialsPayload(form);
		payload.serviceCredentialScopes =
			payload.serviceCredentialProvider === "google_service_account"
				? parseServiceCredentialScopes(form.serviceCredentialScopes ?? "")
				: [];
	}
	return payload;
}

export function buildServiceCredentialsPayload(
	form: Pick<
		MCPServerCreateFormValues,
		| "serviceCredentialProvider"
		| "serviceCredentialsJson"
		| "serviceHeaders"
	>,
): string | undefined {
	if (form.serviceCredentialProvider === "custom_http_headers") {
		return JSON.stringify({
			headers: (form.serviceHeaders ?? []).map((header) => ({
				name: header.name.trim(),
				value: header.value,
			})),
		});
	}
	return form.serviceCredentialsJson;
}

export function validateServiceHeaders(
	headers: { name: string; value: string }[] | undefined,
): string | undefined {
	if (!headers || headers.length === 0) return "Add at least one HTTP header.";
	if (headers.some((header) => !header.name.trim())) {
		return "Every HTTP header needs a name.";
	}
	const names = headers.map((header) => header.name.trim().toLowerCase());
	if (new Set(names).size !== names.length) {
		return "HTTP header names must be unique.";
	}
	return undefined;
}

export function parseServiceCredentialScopes(value: string): string[] {
	return Array.from(
		new Set(
			value
				.split(/[\s,]+/)
				.map((scope) => scope.trim())
				.filter(Boolean),
		),
	);
}

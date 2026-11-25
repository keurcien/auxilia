import {
	MCPAuthType,
	MCPCredentialScope,
	MCPServerCreate,
	OfficialMCPServer,
	ServiceCredentialProvider,
	usesUserCredentials,
} from "@/types/mcp-servers";
import type { ResourceVisibility } from "@/types/visibility";
import {
	buildProviderCredentialsJson,
	EMPTY_SERVICE_CREDENTIAL_FIELDS,
	ServiceCredentialFields,
	ServiceIdentityProvider,
	validateProviderCredentials,
} from "./service-credential-providers";

export interface MCPServerCreateFormValues {
	name: string;
	url: string;
	description: string;
	group: string;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	authType: MCPAuthType;
	// `personal` on api_key / custom_http: each user brings their own secret,
	// and `apiKey` / the header values are the creator's own (optional).
	credentialScope?: MCPCredentialScope;
	apiKey: string;
	oauthClientId: string;
	oauthClientSecret: string;
	serviceCredentialProvider?: ServiceCredentialProvider;
	serviceCredentialsJson?: string;
	serviceCredentialScopes?: string;
	serviceCredentialFields?: ServiceCredentialFields;
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
		officialServer.supportsCimd !== true &&
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
	if (
		officialServer?.requiresUrlConfiguration &&
		form.url.trim() === officialServer.url
	) {
		errors.url = "Replace the example address with your MCP server URL.";
	}
	if (form.visibility === "teams" && (form.teamIds?.length ?? 0) === 0) {
		errors.teamIds = "Select at least one team.";
	}

	const personal = usesUserCredentials(form);

	// The backend rejects shared api_key servers without a key — catch it inline.
	if (form.authType === "api_key" && !personal && !form.apiKey.trim()) {
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
		const provider =
			(form.serviceCredentialProvider as ServiceIdentityProvider | undefined) ??
			"google_service_account";
		const providerError = validateProviderCredentials(
			provider,
			form.serviceCredentialFields ?? EMPTY_SERVICE_CREDENTIAL_FIELDS,
			form.serviceCredentialsJson,
		);
		if (providerError) errors.serviceCredentialsJson = providerError;
	}
	if (form.authType === "custom_http" && personal) {
		const headers = form.serviceHeaders ?? [];
		const headerError =
			validatePersonalHeaderNames(headers.map((header) => header.name)) ??
			(headers.some((header) => header.value.trim()) &&
			headers.some((header) => !header.value.trim())
				? "Fill in every value, or leave them all empty to connect later."
				: undefined);
		if (headerError) errors.serviceHeaders = headerError;
	} else if (form.authType === "custom_http") {
		const headerError = validateServiceHeaders(form.serviceHeaders);
		if (headerError) errors.serviceHeaders = headerError;
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
	const personal = usesUserCredentials(form);
	const apiKey =
		form.authType === "api_key" && !personal
			? form.apiKey || undefined
			: undefined;
	const oauthClientId =
		form.authType === "oauth2" ? form.oauthClientId || undefined : undefined;
	const oauthClientSecret =
		form.authType === "oauth2"
			? form.oauthClientSecret || undefined
			: undefined;
	const payload: MCPServerCreate = {
		name: form.name,
		url: form.url,
		authType: form.authType,
		credentialScope: personal ? "personal" : undefined,
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
		payload.serviceCredentialScopes = parseServiceCredentialScopes(
			form.serviceCredentialScopes ?? "",
		);
	}
	if (form.authType === "api_key" && personal && form.apiKey.trim()) {
		payload.personalCredentials = { apiKey: form.apiKey.trim() };
	}
	if (form.authType === "custom_http" && personal) {
		const headers = (form.serviceHeaders ?? []).map((header) => ({
			name: header.name.trim(),
			value: header.value,
		}));
		payload.personalHeaderNames = headers.map((header) => header.name);
		if (headers.length > 0 && headers.every((header) => header.value.trim())) {
			payload.personalCredentials = { headers };
		}
	} else if (form.authType === "custom_http") {
		payload.serviceCredentialProvider = "custom_http_headers";
		payload.serviceCredentialsJson = buildServiceCredentialsPayload(form);
		payload.serviceCredentialScopes = [];
	}
	return payload;
}

export function buildServiceCredentialsPayload(
	form: Pick<
		MCPServerCreateFormValues,
		| "serviceCredentialProvider"
		| "serviceCredentialsJson"
		| "serviceCredentialFields"
		| "serviceHeaders"
	> & { authType?: MCPAuthType },
): string | undefined {
	if (
		form.authType === "custom_http" ||
		form.serviceCredentialProvider === "custom_http_headers"
	) {
		return JSON.stringify({
			headers: (form.serviceHeaders ?? []).map((header) => ({
				name: header.name.trim(),
				value: header.value,
			})),
		});
	}
	return buildProviderCredentialsJson(
		(form.serviceCredentialProvider ??
			"google_service_account") as ServiceIdentityProvider,
		form.serviceCredentialFields ?? EMPTY_SERVICE_CREDENTIAL_FIELDS,
		form.serviceCredentialsJson,
	);
}

export function validateServiceHeaders(
	headers: { name: string; value: string }[] | undefined,
): string | undefined {
	if (!headers || headers.length === 0) return "Add at least one HTTP header.";
	if (headers.some((header) => !header.name.trim())) {
		return "Every HTTP header needs a name.";
	}
	if (headers.some((header) => !header.value.trim())) {
		return "Every HTTP header needs a value.";
	}
	const names = headers.map((header) => header.name.trim().toLowerCase());
	if (new Set(names).size !== names.length) {
		return "HTTP header names must be unique.";
	}
	return undefined;
}

export function validatePersonalHeaderNames(
	names: string[] | undefined,
): string | undefined {
	const cleaned = (names ?? []).map((name) => name.trim());
	if (cleaned.length === 0) return "Add at least one HTTP header.";
	if (cleaned.some((name) => !name)) return "Every HTTP header needs a name.";
	const lowered = cleaned.map((name) => name.toLowerCase());
	if (new Set(lowered).size !== lowered.length) {
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

import { describe, expect, it } from "vitest";
import {
	buildMCPServerCreatePayload,
	type MCPServerCreateFormValues,
	validateMCPServerCreateForm,
} from "./mcp-server-create-form";

const validForm: MCPServerCreateFormValues = {
	name: "Internal Search",
	url: "https://search.example.com/mcp",
	description: "",
	authType: "none",
	apiKey: "",
	oauthClientId: "",
	oauthClientSecret: "",
	iconUrl: "",
};

describe("buildMCPServerCreatePayload", () => {
	it("builds an API-key server payload and omits empty optional fields", () => {
		const payload = buildMCPServerCreatePayload({
			...validForm,
			authType: "api_key",
			apiKey: "secret-token",
		});

		expect(payload).toEqual({
			name: "Internal Search",
			url: "https://search.example.com/mcp",
			authType: "api_key",
			description: undefined,
			iconUrl: undefined,
			apiKey: "secret-token",
			oauthClientId: undefined,
			oauthClientSecret: undefined,
		});
	});

	it("omits stale OAuth credentials when auth type is not oauth2", () => {
		const payload = buildMCPServerCreatePayload({
			...validForm,
			authType: "none",
			oauthClientId: "stale-client-id",
			oauthClientSecret: "stale-client-secret",
		});

		expect(payload).toEqual({
			name: "Internal Search",
			url: "https://search.example.com/mcp",
			authType: "none",
			description: undefined,
			iconUrl: undefined,
			apiKey: undefined,
			oauthClientId: undefined,
			oauthClientSecret: undefined,
		});
	});

	it("omits stale API key when auth type is not api_key", () => {
		const payload = buildMCPServerCreatePayload({
			...validForm,
			authType: "oauth2",
			apiKey: "stale-api-key",
			oauthClientId: "client-id",
			oauthClientSecret: "client-secret",
		});

		expect(payload).toEqual({
			name: "Internal Search",
			url: "https://search.example.com/mcp",
			authType: "oauth2",
			description: undefined,
			iconUrl: undefined,
			apiKey: undefined,
			oauthClientId: "client-id",
			oauthClientSecret: "client-secret",
		});
	});
});

describe("validateMCPServerCreateForm", () => {
	it("requires a client ID when a custom OAuth server provides a client secret", () => {
		const errors = validateMCPServerCreateForm(
			{
				...validForm,
				authType: "oauth2",
				oauthClientSecret: "client-secret",
			},
			null,
		);

		expect(errors).toEqual({
			oauthClientId:
				"Client ID is required when providing a Client Secret.",
		});
	});

	it("requires a client secret when a custom OAuth server provides a client ID", () => {
		const errors = validateMCPServerCreateForm(
			{
				...validForm,
				authType: "oauth2",
				oauthClientId: "client-id",
			},
			null,
		);

		expect(errors).toEqual({
			oauthClientSecret:
				"Client Secret is required when providing a Client ID.",
		});
	});
});

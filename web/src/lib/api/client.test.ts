import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./client";
import { ApiError } from "./errors";

/** Drive the interceptors without a network: the adapter records the request
 *  it received and answers with whatever the test scripted. */
function scriptAdapter(
	respond: (config: InternalAxiosRequestConfig) => Partial<AxiosResponse>,
) {
	const seen: InternalAxiosRequestConfig[] = [];
	api.defaults.adapter = (config) => {
		seen.push(config);
		const res = respond(config);
		const response: AxiosResponse = {
			data: res.data,
			status: res.status ?? 200,
			statusText: res.statusText ?? "OK",
			headers: res.headers ?? {},
			config,
			request: {},
		};
		if (response.status >= 400) {
			return Promise.reject(
				new AxiosError(
					`Request failed with status code ${response.status}`,
					"ERR_BAD_REQUEST",
					config,
					{},
					response,
				),
			);
		}
		return Promise.resolve(response);
	};
	return seen;
}

afterEach(() => {
	api.defaults.adapter = undefined;
	vi.restoreAllMocks();
});

describe("request conversion", () => {
	it("snake_cases body keys, deeply", async () => {
		const seen = scriptAdapter(() => ({ data: {} }));
		await api.post("/x", { agentId: "a", nested: { modelId: "m" } });
		expect(JSON.parse(seen[0].data as string)).toEqual({
			agent_id: "a",
			nested: { model_id: "m" },
		});
	});

	it("preserves the values under `tools` and `arguments`", async () => {
		const seen = scriptAdapter(() => ({ data: {} }));
		await api.put("/x", {
			tools: { "server-1": { toolName: { requireApproval: true } } },
			arguments: { someKey: 1 },
			otherKey: 2,
		});
		expect(JSON.parse(seen[0].data as string)).toEqual({
			tools: { "server-1": { toolName: { requireApproval: true } } },
			arguments: { someKey: 1 },
			other_key: 2,
		});
	});

	it("snake_cases query params and leaves FormData alone", async () => {
		const seen = scriptAdapter(() => ({ data: {} }));
		const form = new FormData();
		form.append("someFile", "x");
		await api.post("/x", form, { params: { recentSeconds: 30 } });
		expect(seen[0].params).toEqual({ recent_seconds: 30 });
		expect(seen[0].data).toBe(form);
	});
});

describe("response conversion", () => {
	it("camelCases 2xx bodies except under `tools` / `arguments`", async () => {
		scriptAdapter(() => ({
			data: {
				agent_id: "a",
				tools: { "server-1": { tool_name: { require_approval: true } } },
				items: [{ created_at: "t" }],
			},
		}));
		const res = await api.get("/x");
		expect(res.data).toEqual({
			agentId: "a",
			tools: { "server-1": { tool_name: { require_approval: true } } },
			items: [{ createdAt: "t" }],
		});
	});

	it("rejects with an ApiError carrying status, code, detail and the raw body", async () => {
		scriptAdapter(() => ({
			status: 409,
			data: { error: "model_unavailable", model_id: "m", detail: "disabled" },
		}));
		const err = await api.post("/x").catch((e: unknown) => e);
		expect(err).toBeInstanceOf(ApiError);
		const apiErr = err as ApiError;
		expect(apiErr.status).toBe(409);
		expect(apiErr.code).toBe("model_unavailable");
		expect(apiErr.detail).toBe("disabled");
		// Error bodies are the backend's contract as sent — no case conversion.
		expect(apiErr.body).toEqual({
			error: "model_unavailable",
			model_id: "m",
			detail: "disabled",
		});
		expect(apiErr.message).toBe("disabled");
	});

	it("rejects with a status-less ApiError when no response arrived", async () => {
		api.defaults.adapter = (config) =>
			Promise.reject(new AxiosError("Network Error", "ERR_NETWORK", config));
		const err = await api.get("/x").catch((e: unknown) => e);
		expect(err).toBeInstanceOf(ApiError);
		expect((err as ApiError).status).toBeNull();
		expect((err as ApiError).message).toBe("Network Error");
	});
});

import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import * as sandboxesApi from "./sandboxes";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(api.get).mockResolvedValue({ data: "GET" });
	vi.mocked(api.post).mockResolvedValue({ data: "POST" });
	vi.mocked(api.patch).mockResolvedValue({ data: "PATCH" });
	vi.mocked(api.delete).mockResolvedValue({ data: undefined });
});

const save = { name: "lab", description: null, url: "https://sb", config: { a: 1 } };

describe("sandboxes resource", () => {
	it("CRUD", async () => {
		expect(await sandboxesApi.listSandboxes()).toBe("GET");
		expect(api.get).toHaveBeenCalledWith("/sandboxes");
		expect(await sandboxesApi.createSandbox({ ...save, provider: "daytona" })).toBe("POST");
		expect(api.post).toHaveBeenCalledWith("/sandboxes", { ...save, provider: "daytona" });
		expect(await sandboxesApi.updateSandbox("x1", { ...save, secret: "s" })).toBe("PATCH");
		expect(api.patch).toHaveBeenCalledWith("/sandboxes/x1", { ...save, secret: "s" });
	});

	it("delete builds the detach flag as a query param, only when asked", async () => {
		await sandboxesApi.deleteSandbox("x1");
		expect(api.delete).toHaveBeenCalledWith("/sandboxes/x1", { params: undefined });
		await sandboxesApi.deleteSandbox("x1", { detachAgents: true });
		expect(api.delete).toHaveBeenCalledWith("/sandboxes/x1", { params: { detachAgents: true } });
	});

	it("agents and secret hint", async () => {
		await sandboxesApi.listSandboxAgents("x1");
		expect(api.get).toHaveBeenCalledWith("/sandboxes/x1/agents");
		await sandboxesApi.getSandboxSecretHint("x1");
		expect(api.get).toHaveBeenCalledWith("/sandboxes/x1/secret-hint");
	});
});

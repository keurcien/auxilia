import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import {
	clearDefaultModel,
	listManagedModels,
	listModels,
	setDefaultModel,
	setModelEnabled,
	syncWhitelist,
} from "./models";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
	vi.resetAllMocks();
});

describe("models resource", () => {
	it("lists enabled models and the managed catalog", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [{ id: "m1" }] });
		expect(await listModels()).toEqual([{ id: "m1" }]);
		expect(api.get).toHaveBeenCalledWith("/model-providers/models");

		vi.mocked(api.get).mockResolvedValue({ data: [{ modelId: "m1", isEnabled: true }] });
		expect(await listManagedModels()).toEqual([{ modelId: "m1", isEnabled: true }]);
		expect(api.get).toHaveBeenLastCalledWith("/model-providers/models/manage");
	});

	it("enables a model, URL-encoding provider and id", async () => {
		vi.mocked(api.put).mockResolvedValue({ data: undefined });
		await setModelEnabled("openai", "gpt/4o mini", false);
		expect(api.put).toHaveBeenCalledWith(
			"/model-providers/models/openai/gpt%2F4o%20mini",
			{ isEnabled: false },
		);
	});

	it("sets and clears the workspace default", async () => {
		vi.mocked(api.put).mockResolvedValue({ data: undefined });
		await setDefaultModel("anthropic", "claude");
		expect(api.put).toHaveBeenCalledWith("/model-providers/models/default", {
			provider: "anthropic",
			modelId: "claude",
		});

		vi.mocked(api.delete).mockResolvedValue({ data: undefined });
		await clearDefaultModel();
		expect(api.delete).toHaveBeenCalledWith("/model-providers/models/default");
	});

	it("syncs the whitelist and returns the diff", async () => {
		const result = { added: ["a"], removed: [], modelCount: 12, fetchedAt: "now" };
		vi.mocked(api.post).mockResolvedValue({ data: result });
		expect(await syncWhitelist()).toBe(result);
		expect(api.post).toHaveBeenCalledWith("/model-providers/whitelist/sync");
	});
});

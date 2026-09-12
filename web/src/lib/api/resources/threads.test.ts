import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import {
	createThread,
	deleteThread,
	listAgentThreads,
	listThreadRuns,
	listThreads,
	readThread,
	renameThread,
} from "./threads";
import { listActiveRuns } from "./runs";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
	vi.resetAllMocks();
});

describe("threads resource", () => {
	it("lists the caller's threads with paging params and unwraps the page", async () => {
		const page = { items: [], total: 0, limit: 30, offset: 0 };
		vi.mocked(api.get).mockResolvedValue({ data: page });
		expect(await listThreads({ limit: 30, offset: 0 })).toBe(page);
		expect(api.get).toHaveBeenCalledWith("/threads", {
			params: { limit: 30, offset: 0 },
		});
	});

	it("lists an agent's threads", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: { items: [] } });
		await listAgentThreads("a1", { limit: 20, offset: 40 });
		expect(api.get).toHaveBeenCalledWith("/agents/a1/threads", {
			params: { limit: 20, offset: 40 },
		});
	});

	it("reads thread metadata and the viewer role", async () => {
		const read = { thread: { id: "t1" }, viewerRole: "admin" };
		vi.mocked(api.get).mockResolvedValue({ data: read });
		expect(await readThread("t1")).toBe(read);
		expect(api.get).toHaveBeenCalledWith("/threads/t1");
	});

	it("creates, renames and deletes", async () => {
		vi.mocked(api.post).mockResolvedValue({ data: { id: "t1" } });
		const payload = { id: "t1", agentId: "a1", modelId: "m", reasoningEffort: null };
		expect(await createThread(payload)).toEqual({ id: "t1" });
		expect(api.post).toHaveBeenCalledWith("/threads", payload);

		vi.mocked(api.patch).mockResolvedValue({ data: {} });
		await renameThread("t1", "New title");
		expect(api.patch).toHaveBeenCalledWith("/threads/t1", {
			firstMessageContent: "New title",
		});

		vi.mocked(api.delete).mockResolvedValue({ data: undefined });
		await deleteThread("t1");
		expect(api.delete).toHaveBeenCalledWith("/threads/t1");
	});

	it("lists a thread's runs", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [{ id: "r1" }] });
		expect(await listThreadRuns("t1")).toEqual([{ id: "r1" }]);
		expect(api.get).toHaveBeenCalledWith("/threads/t1/runs");
	});
});

describe("runs resource", () => {
	it("polls active runs with the recently-finished window", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [] });
		await listActiveRuns(35);
		expect(api.get).toHaveBeenCalledWith("/runs/active", {
			params: { recentSeconds: 35 },
		});
	});
});

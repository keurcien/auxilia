import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import {
	createTrigger,
	deleteTrigger,
	getTrigger,
	listTriggerThreads,
	listTriggers,
	previewSchedule,
	runTrigger,
	updateTrigger,
} from "./triggers";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
	vi.resetAllMocks();
});

describe("triggers resource", () => {
	it("lists and reads, forwarding a server-side cookie when given", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [{ id: "tr1" }] });
		expect(await listTriggers()).toEqual([{ id: "tr1" }]);
		expect(api.get).toHaveBeenCalledWith("/triggers");

		vi.mocked(api.get).mockResolvedValue({ data: { id: "tr1" } });
		expect(await getTrigger("tr1")).toEqual({ id: "tr1" });
		expect(api.get).toHaveBeenLastCalledWith("/triggers/tr1", { headers: undefined });

		await getTrigger("tr1", { cookie: "session=abc" });
		expect(api.get).toHaveBeenLastCalledWith("/triggers/tr1", {
			headers: { Cookie: "session=abc" },
		});
	});

	it("creates, updates and deletes", async () => {
		const payload = {
			name: "Nightly",
			instructions: "Do it",
			agentId: "a1",
			modelId: "m",
			cronExpression: "0 2 * * *",
			timezone: "Europe/Paris",
		};
		vi.mocked(api.post).mockResolvedValue({ data: { id: "tr1", ...payload } });
		expect(await createTrigger(payload)).toMatchObject({ id: "tr1" });
		expect(api.post).toHaveBeenCalledWith("/triggers", payload);

		vi.mocked(api.patch).mockResolvedValue({ data: { id: "tr1", isActive: false } });
		expect(await updateTrigger("tr1", { isActive: false })).toEqual({ id: "tr1", isActive: false });
		expect(api.patch).toHaveBeenCalledWith("/triggers/tr1", { isActive: false });

		vi.mocked(api.delete).mockResolvedValue({ data: undefined });
		await deleteTrigger("tr1");
		expect(api.delete).toHaveBeenCalledWith("/triggers/tr1");
	});

	it("fires a trigger and lists its past firings", async () => {
		vi.mocked(api.post).mockResolvedValue({ data: { threadId: "t1", runId: "r1" } });
		expect(await runTrigger("tr1")).toEqual({ threadId: "t1", runId: "r1" });
		expect(api.post).toHaveBeenCalledWith("/triggers/tr1/run");

		vi.mocked(api.get).mockResolvedValue({ data: [{ id: "t1" }] });
		expect(await listTriggerThreads("tr1")).toEqual([{ id: "t1" }]);
		expect(api.get).toHaveBeenCalledWith("/triggers/tr1/threads");
	});

	it("previews a schedule, three runs by default", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: { nextRunAts: ["2026-09-13T02:00:00Z"] } });
		expect(await previewSchedule("0 2 * * *", "Europe/Paris")).toEqual({
			nextRunAts: ["2026-09-13T02:00:00Z"],
		});
		expect(api.get).toHaveBeenCalledWith("/triggers/schedule/preview", {
			params: { cronExpression: "0 2 * * *", timezone: "Europe/Paris", count: 3 },
		});
		await previewSchedule("0 2 * * *", "UTC", 5);
		expect(api.get).toHaveBeenLastCalledWith("/triggers/schedule/preview", {
			params: { cronExpression: "0 2 * * *", timezone: "UTC", count: 5 },
		});
	});
});

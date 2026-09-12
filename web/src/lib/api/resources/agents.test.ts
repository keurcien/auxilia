import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import * as agentsApi from "./agents";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

const payload: agentsApi.AgentWrite = {
	name: "Helper",
	instructions: "Be helpful",
	description: null,
	emoji: null,
	color: null,
	mcpServers: [],
	sandboxes: [],
	subagentIds: [],
};

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(api.get).mockResolvedValue({ data: {} });
	vi.mocked(api.post).mockResolvedValue({ data: {} });
	vi.mocked(api.put).mockResolvedValue({ data: {} });
	vi.mocked(api.patch).mockResolvedValue({ data: {} });
	vi.mocked(api.delete).mockResolvedValue({ data: undefined });
});

describe("agents resource", () => {
	it("lists live and archived agents", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [{ id: "a1" }] });
		expect(await agentsApi.listAgents()).toEqual([{ id: "a1" }]);
		expect(api.get).toHaveBeenCalledWith("/agents");
		await agentsApi.listArchivedAgents();
		expect(api.get).toHaveBeenCalledWith("/agents", { params: { archived: true } });
	});

	it("reads one agent, forwarding a server-side cookie when given", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: { id: "a1" } });
		expect(await agentsApi.getAgent("a1")).toEqual({ id: "a1" });
		expect(api.get).toHaveBeenCalledWith("/agents/a1", { headers: undefined });
		await agentsApi.getAgent("a1", { cookie: "session=x" });
		expect(api.get).toHaveBeenCalledWith("/agents/a1", { headers: { Cookie: "session=x" } });
	});

	it("creates and saves the configuration atomically", async () => {
		vi.mocked(api.post).mockResolvedValue({ data: { id: "new" } });
		expect(await agentsApi.createAgent(payload)).toEqual({ id: "new" });
		expect(api.post).toHaveBeenCalledWith("/agents", payload);

		vi.mocked(api.put).mockResolvedValue({ data: { id: "a1" } });
		expect(await agentsApi.saveAgentConfig("a1", payload)).toEqual({ id: "a1" });
		expect(api.put).toHaveBeenCalledWith("/agents/a1/config", payload);
	});

	it("patches the tag, archives, restores and hard-deletes", async () => {
		await agentsApi.patchAgent("a1", { tagId: "t1" });
		expect(api.patch).toHaveBeenCalledWith("/agents/a1", { tagId: "t1" });
		await agentsApi.archiveAgent("a1");
		expect(api.delete).toHaveBeenCalledWith("/agents/a1");
		await agentsApi.restoreAgent("a1");
		expect(api.post).toHaveBeenCalledWith("/agents/a1/restore");
		await agentsApi.permanentlyDeleteAgent("a1");
		expect(api.delete).toHaveBeenCalledWith("/agents/a1/permanent");
	});

	it("reads readiness", async () => {
		const readiness = { ready: false, disconnectedServers: ["s1"], status: "disconnected" };
		vi.mocked(api.get).mockResolvedValue({ data: readiness });
		expect(await agentsApi.getAgentReadiness("a1")).toBe(readiness);
		expect(api.get).toHaveBeenCalledWith("/agents/a1/is-ready");
	});

	it("reads and replaces permissions and team bindings", async () => {
		const rows = [{ userId: "u1", permission: "editor" as const }];
		vi.mocked(api.get).mockResolvedValueOnce({ data: rows }).mockResolvedValueOnce({ data: { teamIds: ["t1"] } });
		expect(await agentsApi.listAgentPermissions("a1")).toBe(rows);
		expect(api.get).toHaveBeenCalledWith("/agents/a1/permissions");
		expect(await agentsApi.listAgentTeamIds("a1")).toEqual(["t1"]);
		expect(api.get).toHaveBeenCalledWith("/agents/a1/teams");

		await agentsApi.setAgentPermissions("a1", rows);
		expect(api.put).toHaveBeenCalledWith("/agents/a1/permissions", rows);
		await agentsApi.setAgentTeamIds("a1", ["t1", "t2"]);
		expect(api.put).toHaveBeenCalledWith("/agents/a1/teams", { teamIds: ["t1", "t2"] });
	});

	it("manages the tag vocabulary", async () => {
		vi.mocked(api.get).mockResolvedValue({ data: [{ id: "t1", name: "Ops" }] });
		expect(await agentsApi.listTags()).toEqual([{ id: "t1", name: "Ops" }]);
		expect(api.get).toHaveBeenCalledWith("/tags/");
		await agentsApi.createTag("Ops");
		expect(api.post).toHaveBeenCalledWith("/tags/", { name: "Ops" });
		await agentsApi.renameTag("t1", "Operations");
		expect(api.patch).toHaveBeenCalledWith("/tags/t1", { name: "Operations" });
		await agentsApi.deleteTag("t1");
		expect(api.delete).toHaveBeenCalledWith("/tags/t1");
	});
});

import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import * as mcpServersApi from "./mcp-servers";

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

describe("mcp-servers resource", () => {
	it("CRUD", async () => {
		expect(await mcpServersApi.listMcpServers()).toBe("GET");
		expect(api.get).toHaveBeenCalledWith("/mcp-servers");

		await mcpServersApi.getMcpServer("s1");
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/s1", { headers: undefined });
		await mcpServersApi.getMcpServer("s1", { cookie: "session=abc" });
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/s1", {
			headers: { Cookie: "session=abc" },
		});

		const create = { name: "n", url: "https://x/mcp", authType: "none" as const };
		expect(await mcpServersApi.createMcpServer(create)).toBe("POST");
		expect(api.post).toHaveBeenCalledWith("/mcp-servers", create);

		expect(await mcpServersApi.updateMcpServer("s1", { name: "m" })).toBe("PATCH");
		expect(api.patch).toHaveBeenCalledWith("/mcp-servers/s1", { name: "m" });
	});

	it("delete builds the detach flag as a query param, only when asked", async () => {
		await mcpServersApi.deleteMcpServer("s1");
		expect(api.delete).toHaveBeenCalledWith("/mcp-servers/s1", { params: undefined });
		await mcpServersApi.deleteMcpServer("s1", { detachAgents: true });
		expect(api.delete).toHaveBeenCalledWith("/mcp-servers/s1", {
			params: { detachAgents: true },
		});
	});

	it("connection probes", async () => {
		await mcpServersApi.listMcpServerTools("s1");
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/s1/list-tools");

		vi.mocked(api.get).mockResolvedValueOnce({ data: { connected: true } });
		expect(await mcpServersApi.isMcpServerConnected("s1")).toBe(true);
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/s1/is-connected");
		vi.mocked(api.get).mockResolvedValueOnce({ data: {} });
		expect(await mcpServersApi.isMcpServerConnected("s1")).toBe(false);

		await mcpServersApi.testMcpServerConnection("s1");
		expect(api.post).toHaveBeenCalledWith("/mcp-servers/s1/test-connection");
		await mcpServersApi.testMcpConnection({ url: "u", authType: "api_key", apiKey: "k" });
		expect(api.post).toHaveBeenCalledWith("/mcp-servers/test-connection", {
			url: "u",
			authType: "api_key",
			apiKey: "k",
		});
		await mcpServersApi.resetMcpServerConnections("s1");
		expect(api.post).toHaveBeenCalledWith("/mcp-servers/s1/reset");
	});

	it("admin views: agents, connections, secret hint", async () => {
		await mcpServersApi.listMcpServerAgents("s1");
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/s1/agents");
		await mcpServersApi.listMcpServerConnections("s1");
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/s1/connections");
		await mcpServersApi.deleteMcpServerConnection("s1", "u9");
		expect(api.delete).toHaveBeenCalledWith("/mcp-servers/s1/connections/u9");
		const signal = new AbortController().signal;
		await mcpServersApi.getMcpServerOAuthSecretHint("s1", { signal });
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/s1/oauth-secret-hint", { signal });
	});

	it("catalog", async () => {
		const signal = new AbortController().signal;
		await mcpServersApi.listOfficialMcpServers({ signal });
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/official", { signal });
		await mcpServersApi.listOfficialMcpServers();
		expect(api.get).toHaveBeenCalledWith("/mcp-servers/official", { signal: undefined });
		expect(await mcpServersApi.syncMcpCatalog()).toBe("POST");
		expect(api.post).toHaveBeenCalledWith("/mcp-servers/catalog/sync");
	});

	it("sync-tools on the agent binding", async () => {
		await mcpServersApi.syncAgentMcpServerTools("a1", "s1");
		expect(api.post).toHaveBeenCalledWith("/agents/a1/mcp-servers/s1/sync-tools");
	});
});

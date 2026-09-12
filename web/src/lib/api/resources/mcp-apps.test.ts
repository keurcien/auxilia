import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api/client";
import { callMcpAppTool, readMcpAppResource } from "./mcp-apps";

vi.mock("@/lib/api/client", () => ({
	api: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(api.post).mockResolvedValue({ data: { ok: 1 } });
});

describe("mcp-apps resource", () => {
	it("reads a resource on the app's behalf", async () => {
		expect(await readMcpAppResource("s1", "ui://app/main")).toEqual({ ok: 1 });
		expect(api.post).toHaveBeenCalledWith("/mcp-servers/s1/app/read-resource", {
			uri: "ui://app/main",
		});
	});

	it("calls a tool with its arguments as authored (null when absent)", async () => {
		await callMcpAppTool("s1", "search", { q: "x" });
		expect(api.post).toHaveBeenCalledWith("/mcp-servers/s1/app/call-tool", {
			toolName: "search",
			arguments: { q: "x" },
		});
		await callMcpAppTool("s1", "search", null);
		expect(api.post).toHaveBeenLastCalledWith("/mcp-servers/s1/app/call-tool", {
			toolName: "search",
			arguments: null,
		});
	});
});

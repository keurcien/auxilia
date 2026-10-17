import { beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api/client";
import { decideSandboxMcp, pendingSandboxMcp, type SandboxMcpRequest } from "./sandbox-mcp";

vi.mock("@/lib/api/client", () => ({ api: { get: vi.fn(), post: vi.fn() } }));
beforeEach(() => { vi.resetAllMocks(); });

describe("sandbox MCP resource", () => {
  it("passes the pending URL and abort signal", async () => {
    const signal = new AbortController().signal;
    vi.mocked(api.get).mockResolvedValue({ data: [] });
    expect(await pendingSandboxMcp("thread-id", signal)).toEqual([]);
    expect(api.get).toHaveBeenCalledWith("/threads/thread-id/sandbox-mcp/pending", { signal });
  });
  it("addresses the decision by scope, operation and phase", async () => {
    const request: SandboxMcpRequest = { id: "operation", scope: "scope", phase: "phase", agent: "agent", tool: "write", arguments: {}, status: "approval_required" };
    vi.mocked(api.post).mockResolvedValue({ data: undefined });
    await decideSandboxMcp("thread-id", request, "reject");
    expect(api.post).toHaveBeenCalledWith("/threads/thread-id/sandbox-mcp/scope/operation/decision", { type: "reject", phase: "phase" });
  });
});

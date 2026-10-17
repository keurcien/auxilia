import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toHttpUrl } from "@/lib/urls/http";
import { SandboxMcpRequests } from "./sandbox-mcp-requests";
import { decideSandboxMcp, pendingSandboxMcp } from "@/lib/api/resources/sandbox-mcp";

vi.mock("@/lib/api/resources/sandbox-mcp", () => ({
  decideSandboxMcp: vi.fn(),
  pendingSandboxMcp: vi.fn(),
}));

const request = { id: "op", scope: "scope", phase: "phase", agent: "CRM", tool: "crm_write", arguments: { CustomerID: 42 }, status: "approval_required" as const };

beforeEach(() => { vi.clearAllMocks(); });

describe("sandbox MCP requests", () => {
  it("shows pending approval while execute is running and submits the exact request", async () => {
    vi.mocked(pendingSandboxMcp).mockResolvedValue([request]);
    vi.mocked(decideSandboxMcp).mockResolvedValue(undefined);
    render(<SandboxMcpRequests threadId="thread" enabled />);
    const approve = await screen.findByRole("button", { name: "Approve" });
    expect(screen.getByText(/CustomerID/)).toBeDefined();
    fireEvent.click(approve);
    await waitFor(() => { expect(decideSandboxMcp).toHaveBeenCalledWith("thread", request, "approve"); });
  });

  it("offers connect and cancellation for OAuth without approving the MCP action", async () => {
    vi.mocked(pendingSandboxMcp).mockResolvedValue([{ ...request, status: "oauth_required", authUrl: "https://auth.example/connect" }]);
    render(<SandboxMcpRequests threadId="thread" enabled />);
    expect(await screen.findByRole("button", { name: "Connect" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(decideSandboxMcp).not.toHaveBeenCalled();
  });

  it("does not fetch for inactive or read-only sessions", () => {
    render(<SandboxMcpRequests threadId="thread" enabled={false} />);
    expect(pendingSandboxMcp).not.toHaveBeenCalled();
  });

  it("clears a transient poll error after the next successful five-second poll", async () => {
    vi.useFakeTimers();
    try {
      vi.mocked(pendingSandboxMcp).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([]);
      render(<SandboxMcpRequests threadId="thread" enabled />);
      await act(async () => {});
      expect(screen.getByRole("alert")).toBeDefined();
      await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
      expect(pendingSandboxMcp).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole("alert")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("rejects executable authorization URLs", () => {
    expect(toHttpUrl("javascript:alert(1)")).toBeNull();
    expect(toHttpUrl("data:text/html,test")).toBeNull();
    expect(toHttpUrl("https://auth.example/connect")).toBe("https://auth.example/connect");
  });
});

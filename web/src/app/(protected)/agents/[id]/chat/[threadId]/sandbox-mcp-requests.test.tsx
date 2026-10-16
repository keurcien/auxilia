import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SandboxMcpRequests, safeOAuthUrl } from "./sandbox-mcp-requests";
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

  it("rejects executable authorization URLs", () => {
    expect(safeOAuthUrl("javascript:alert(1)")).toBeNull();
    expect(safeOAuthUrl("data:text/html,test")).toBeNull();
    expect(safeOAuthUrl("https://auth.example/connect")).toBe("https://auth.example/connect");
  });
});

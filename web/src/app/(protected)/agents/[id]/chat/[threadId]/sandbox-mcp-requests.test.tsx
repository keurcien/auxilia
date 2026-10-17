import type { Interrupt } from "@langchain/langgraph-sdk";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { toHttpUrl } from "@/lib/urls/http";
import { SandboxMcpRequests, sandboxMcpRequest } from "./sandbox-mcp-requests";

const approval: Interrupt = {
  id: "wait-1",
  namespace: ["sandbox-mcp"],
  value: {
    action_requests: [{ name: "crm_write", args: { CustomerID: 42 } }],
    sandbox_mcp: { operation_id: "op", agent: "CRM", status: "approval_required", auth_url: null },
  },
};

const oauth: Interrupt = {
  id: "wait-2",
  namespace: ["sandbox-mcp"],
  value: {
    action_requests: [{ name: "crm_read", args: {} }],
    sandbox_mcp: { operation_id: "op-2", agent: "CRM", status: "oauth_required", auth_url: "https://auth.example/connect" },
  },
};

const graphApproval: Interrupt = { id: "ab".repeat(16), namespace: [], value: { action_requests: [{ name: "crm_write", args: {} }] } };

describe("sandbox MCP requests", () => {
  it("answers an approval through input.respond, addressed by the interrupt", async () => {
    const respond = vi.fn().mockResolvedValue(undefined);
    render(<SandboxMcpRequests interrupts={[approval, graphApproval]} respond={respond} enabled />);
    expect(screen.getByText(/CustomerID/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(respond).toHaveBeenCalledWith({ decisions: [{ tool_call_id: "op", type: "approve" }] }, "wait-1");
    await waitFor(() => { expect(screen.getByRole("button", { name: "Approve" }).hasAttribute("disabled")).toBe(false); });
  });

  it("keeps the card and shows the error when the decision is not accepted", async () => {
    const respond = vi.fn().mockRejectedValue(new Error("offline"));
    render(<SandboxMcpRequests interrupts={[approval]} respond={respond} enabled />);
    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(await screen.findByRole("alert")).toBeDefined();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDefined();
  });

  it("offers connect and cancellation for OAuth without approving the MCP action", () => {
    const respond = vi.fn().mockResolvedValue(undefined);
    render(<SandboxMcpRequests interrupts={[oauth]} respond={respond} enabled />);
    expect(screen.getByRole("button", { name: "Connect" })).toBeDefined();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(respond).toHaveBeenCalledWith({ decisions: [{ tool_call_id: "op-2", type: "reject" }] }, "wait-2");
  });

  it("ignores the graph's own interrupts and read-only sessions", () => {
    expect(sandboxMcpRequest(graphApproval)).toBeNull();
    const { container } = render(<SandboxMcpRequests interrupts={[approval]} respond={vi.fn()} enabled={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("rejects executable authorization URLs", () => {
    expect(toHttpUrl("javascript:alert(1)")).toBeNull();
    expect(toHttpUrl("data:text/html,test")).toBeNull();
    expect(toHttpUrl("https://auth.example/connect")).toBe("https://auth.example/connect");
  });
});

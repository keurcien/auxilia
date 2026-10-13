import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { JSONRPCRequest } from "@modelcontextprotocol/sdk/types.js";
import { McpAppWidget } from "./mcp-app-widget";

type Fallback = (request: JSONRPCRequest) => Promise<Record<string, unknown>>;
const renderer = vi.hoisted(() => ({
  props: {} as { onFallbackRequest?: Fallback; hostContext?: Record<string, unknown> },
}));
vi.mock("@mcp-ui/client", () => ({
  AppRenderer: (props: typeof renderer.props) => {
    renderer.props = props;
    return null;
  },
}));

const request = (method: string, params?: Record<string, unknown>): JSONRPCRequest => ({
  jsonrpc: "2.0",
  id: 1,
  method,
  params,
});
const app = {
  toolName: "show_dashboard",
  appToolInfo: { resourceUri: "ui://dashboard", serverId: "server" },
};

describe("McpAppWidget display modes", () => {
  it("tells the app its mode and answers ui/request-display-mode", async () => {
    const onRequestDisplayMode = vi.fn(() => "fullscreen" as const);
    render(<McpAppWidget {...app} onRequestDisplayMode={onRequestDisplayMode} />);
    expect(renderer.props.hostContext).toMatchObject({
      displayMode: "inline",
      availableDisplayModes: ["inline", "fullscreen"],
    });
    const fallback = renderer.props.onFallbackRequest!;
    await expect(
      fallback(request("ui/request-display-mode", { mode: "fullscreen" })),
    ).resolves.toEqual({ mode: "fullscreen" });
    expect(onRequestDisplayMode).toHaveBeenCalledWith("fullscreen");
    await expect(fallback(request("ui/unknown"))).rejects.toThrow(/No handler/);
  });
  it("keeps its mode when the host cannot change it", async () => {
    render(<McpAppWidget {...app} displayMode="fullscreen" />);
    await expect(
      renderer.props.onFallbackRequest!(
        request("ui/request-display-mode", { mode: "pip" }),
      ),
    ).resolves.toEqual({ mode: "fullscreen" });
  });
});

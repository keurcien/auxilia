import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppSlot, ArtifactCards, ArtifactWorkspace } from "./workspace";
import { listArtifacts, readArtifact } from "@/lib/api/resources/artifacts";
import type { Artifact } from "@/lib/api/resources/artifacts";
import { useChatHeaderStore } from "@/stores/chat-header-store";

vi.mock("@/lib/api/resources/artifacts", () => ({
  listArtifacts: vi.fn(),
  readArtifact: vi.fn(),
  contentUrl: () => "/download",
}));
vi.mock("./viewers", () => ({
  ArtifactViewer: () => <div>File preview</div>,
  Loading: ({ label }: { label: string }) => <div role="status">{label}</div>,
}));
// What the workspace answered to each `ui/request-display-mode`.
const replies = vi.hoisted((): string[] => []);
vi.mock("@/app/(protected)/agents/[id]/chat/components/mcp-app-widget", () => ({
  McpAppWidget: ({
    displayMode = "inline",
    onRequestDisplayMode,
  }: {
    displayMode?: string;
    onRequestDisplayMode?: (mode: string) => string;
  }) => (
    <div>
      {`App ${displayMode}`}
      <button
        type="button"
        onClick={() => {
          const reply = onRequestDisplayMode?.(
            displayMode === "inline" ? "fullscreen" : "inline",
          );
          if (reply) replies.push(reply);
        }}
      >
        Request mode
      </button>
    </div>
  ),
}));
const app = {
  toolName: "show_dashboard",
  appToolInfo: { resourceUri: "ui://dashboard", serverId: "server" },
  serverName: "Metabase",
};
const item: Artifact = {
  id: "file",
  thread_id: "thread",
  tool_call_id: "call",
  title: "Report",
  filename: "report.csv",
  mime_type: "text/csv",
  size: 3,
  temporary: true,
  created_at: null,
};

beforeEach(() => {
  vi.resetAllMocks();
  // Stand-in for the chat header's actions slot the Files button portals into.
  const slot = document.createElement("div");
  document.body.appendChild(slot);
  useChatHeaderStore.getState().setActionsEl(slot);
  vi.mocked(listArtifacts).mockResolvedValue([item]);
  vi.mocked(readArtifact).mockResolvedValue(new ArrayBuffer(3));
});
describe("artifact workspace", () => {
  it("rehydrates cards, opens the side panel and explains temporary retention", async () => {
    render(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="">
        <ArtifactCards toolCallId="call" />
      </ArtifactWorkspace>,
    );
    fireEvent.click(await screen.findByText("Report"));
    expect(await screen.findByText("File preview")).toBeInTheDocument();
    expect(screen.getByText(/temporary — download to keep/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Close artifact viewer"));
    expect(screen.queryByLabelText("Artifact viewer")).toBeNull();
  });
  it("keeps the card and shows missing-file feedback", async () => {
    vi.mocked(readArtifact).mockRejectedValue(
      new Error("This temporary file expired with its execution environment."),
    );
    render(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="">
        Chat
      </ArtifactWorkspace>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Artifacts/ }));
    fireEvent.click(await screen.findByText("Report"));
    expect(await screen.findByRole("alert")).toHaveTextContent("expired");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
  it("lists thread files and returns to the list from the previewer", async () => {
    render(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="">
        Chat
      </ArtifactWorkspace>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Artifacts/ }));
    expect(screen.getByText("Artifacts in this thread")).toBeInTheDocument();
    expect(screen.getByText(/Files are temporary/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Report"));
    expect(await screen.findByText("File preview")).toBeInTheDocument();
    expect(screen.getByText(/1 of 1 artifacts/)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Back to artifacts"));
    expect(screen.getByText("Artifacts in this thread")).toBeInTheDocument();
  });
  it("opens an inline MCP app in the panel and collapses it to a card", async () => {
    render(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="">
        <AppSlot toolCallId="app-call" app={app} />
      </ArtifactWorkspace>,
    );
    expect(screen.getByText("App inline")).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("Open Show dashboard in panel"));
    const panel = screen.getByLabelText("Artifact viewer");
    expect(within(panel).getByText("App fullscreen")).toBeInTheDocument();
    // Exactly one copy runs: the inline spot is now a card.
    expect(screen.queryByText("App inline")).toBeNull();
    expect(screen.getAllByText("Show dashboard")).toHaveLength(2);
    fireEvent.click(screen.getByLabelText("Close artifact viewer"));
    expect(screen.getByText("App inline")).toBeInTheDocument();
  });
  it("answers the app's display-mode requests", async () => {
    render(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="">
        <AppSlot toolCallId="app-call" app={app} />
      </ArtifactWorkspace>,
    );
    replies.length = 0;
    fireEvent.click(screen.getByText("Request mode"));
    expect(screen.getByText("App fullscreen")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Request mode"));
    expect(screen.queryByLabelText("Artifact viewer")).toBeNull();
    expect(screen.getByText("App inline")).toBeInTheDocument();
    // The reply is the mode now in effect, as the MCP Apps spec requires.
    expect(replies).toEqual(["fullscreen", "inline"]);
  });
  it("never replaces an artifacts list the user opened", async () => {
    const next: Artifact = { ...item, id: "next", title: "Next" };
    const { rerender } = render(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="1">
        Chat
      </ArtifactWorkspace>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Artifacts/ }));
    vi.mocked(listArtifacts).mockResolvedValue([item, next]);
    rerender(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="2">
        Chat
      </ArtifactWorkspace>,
    );
    expect(await screen.findByText("Next")).toBeInTheDocument();
    expect(screen.getByText("Artifacts in this thread")).toBeInTheDocument();
    expect(screen.queryByText("File preview")).toBeNull();
  });
  it("lists apps with files in transcript order", async () => {
    render(
      <ArtifactWorkspace
        threadId="thread"
        running={false}
        refreshKey=""
        order={["call", "app-call"]}
      >
        <AppSlot toolCallId="app-call" app={app} />
      </ArtifactWorkspace>,
    );
    fireEvent.click(await screen.findByRole("button", { name: /Artifacts\s*2/ }));
    const rows = within(screen.getByRole("list")).getAllByRole("button");
    expect(rows[0]).toHaveTextContent("Show dashboard");
    expect(rows[0]).toHaveTextContent("Metabase");
    expect(rows[1]).toHaveTextContent("Report");
    fireEvent.click(rows[0]);
    expect(screen.getByText(/1 of 2 artifacts/)).toBeInTheDocument();
    expect(screen.getByLabelText("Back to artifacts")).toBeInTheDocument();
  });
  it("auto-opens a new file unless the user picked what the panel shows", async () => {
    const next: Artifact = { ...item, id: "next", title: "Next" };
    const { rerender } = render(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="1">
        <AppSlot toolCallId="app-call" app={app} />
      </ArtifactWorkspace>,
    );
    await screen.findByRole("button", { name: /Artifacts/ });
    fireEvent.click(screen.getByLabelText("Open Show dashboard in panel"));
    vi.mocked(listArtifacts).mockResolvedValue([item, next]);
    rerender(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="2">
        <AppSlot toolCallId="app-call" app={app} />
      </ArtifactWorkspace>,
    );
    expect(await screen.findByRole("button", { name: /Artifacts\s*3/ })).toBeInTheDocument();
    expect(screen.getByText("App fullscreen")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Close artifact viewer"));
    vi.mocked(listArtifacts).mockResolvedValue([item, next, { ...next, id: "last" }]);
    rerender(
      <ArtifactWorkspace threadId="thread" running={false} refreshKey="3">
        <AppSlot toolCallId="app-call" app={app} />
      </ArtifactWorkspace>,
    );
    expect(await screen.findByText("File preview")).toBeInTheDocument();
  });
});

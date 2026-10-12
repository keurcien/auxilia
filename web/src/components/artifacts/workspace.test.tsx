import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ArtifactCards, ArtifactWorkspace } from "./workspace";
import { listArtifacts, readArtifact } from "@/lib/api/resources/artifacts";
import type { Artifact } from "@/lib/api/resources/artifacts";

vi.mock("@/lib/api/resources/artifacts", () => ({
  listArtifacts: vi.fn(),
  readArtifact: vi.fn(),
  contentUrl: () => "/download",
}));
vi.mock("./viewers", () => ({ ArtifactViewer: () => <div>File preview</div> }));
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
    await waitFor(() => {
      expect(screen.getAllByText("Report")).toHaveLength(2);
    });
    fireEvent.click(screen.getAllByText("Report")[0]);
    expect(await screen.findByText("File preview")).toBeInTheDocument();
    expect(screen.getByText(/Temporary file —/)).toBeInTheDocument();
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
    fireEvent.click(await screen.findByText("Report"));
    expect(await screen.findByRole("alert")).toHaveTextContent("expired");
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});

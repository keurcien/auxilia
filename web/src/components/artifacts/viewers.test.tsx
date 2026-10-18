import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ArtifactViewer, isolatedHtml, viewers } from "./viewers";
import type { Artifact } from "@/lib/api/resources/artifacts";

vi.mock("@/lib/api/resources/artifacts", () => ({
  getHtmlSources: () => Promise.resolve(["https://cdn.jsdelivr.net"]),
}));

const artifact: Artifact = {
  id: "file",
  thread_id: "thread",
  tool_call_id: "call",
  title: "Report",
  filename: "report.csv",
  mime_type: "text/csv",
  size: 20,
  sha256: "a",
  temporary: true,
  created_at: null,
};
const bytes = (text: string) => new TextEncoder().encode(text).buffer;

describe("artifact viewer adapters", () => {
  it("renders quoted CSV cells as text, including attempted markup", () => {
    render(
      <ArtifactViewer
        artifact={artifact}
        bytes={bytes('Name,Value\n"a,b","<script>alert(1)</script>"')}
      />,
    );
    expect(screen.getByText("a,b")).toBeInTheDocument();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });
  it("uses an opaque HTML iframe with CSP ahead of authored content", async () => {
    render(
      <ArtifactViewer
        artifact={{ ...artifact, mime_type: "text/html" }}
        bytes={bytes('<script>fetch("https://example.com")</script>')}
      />,
    );
    const frame = await screen.findByTitle("HTML artifact");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    const policy = frame.getAttribute("srcdoc");
    expect(policy).toContain("connect-src 'none'");
    // Scripts may load from the workspace's allowed sources, never fetch.
    expect(policy).toContain(
      "script-src 'unsafe-inline' https://cdn.jsdelivr.net;",
    );
    expect(isolatedHtml("", [])).toContain("script-src 'unsafe-inline';");
    const page = isolatedHtml("<script>evil()</script>", []);
    expect(page.indexOf("Content-Security-Policy")).toBeLessThan(
      page.indexOf("<script>"),
    );
  });
  it("falls back to download for unknown content", () => {
    render(
      <ArtifactViewer
        artifact={{ ...artifact, mime_type: "application/octet-stream" }}
        bytes={bytes("binary")}
      />,
    );
    expect(screen.getByText(/Preview unavailable/)).toBeInTheDocument();
  });
  it("renders source files as code, with the text intact", () => {
    render(
      <ArtifactViewer
        artifact={{ ...artifact, mime_type: "text/x-python" }}
        bytes={bytes("print('<b>hi</b>')")}
      />,
    );
    expect(screen.getByText("print('<b>hi</b>')")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    expect(
      viewers.find((viewer) => viewer.supports("application/json"))?.id,
    ).toBe("code");
  });
  it("selects PPTX without using an HTML MIME guess", () => {
    expect(
      viewers.find((viewer) =>
        viewer.supports(
          "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
      )?.id,
    ).toBe("pptx");
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ArtifactViewer, isolatedHtml, viewers } from "./viewers";
import type { Artifact } from "@/lib/api/resources/artifacts";

const artifact: Artifact = {
  id: "file",
  thread_id: "thread",
  tool_call_id: "call",
  title: "Report",
  filename: "report.csv",
  mime_type: "text/csv",
  size: 20,
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
  it("uses an opaque HTML iframe with CSP ahead of authored content", () => {
    render(
      <ArtifactViewer
        artifact={{ ...artifact, mime_type: "text/html" }}
        bytes={bytes('<script>fetch("https://example.com")</script>')}
      />,
    );
    // Scripts are off until the viewer opts in for this file.
    expect(screen.getByTitle("HTML artifact")).toHaveAttribute("sandbox", "");
    fireEvent.click(screen.getByRole("button", { name: /Run scripts/ }));
    const frame = screen.getByTitle("HTML artifact");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame.getAttribute("srcdoc")).toContain("connect-src 'none'");
    expect(
      isolatedHtml("<script>evil()</script>").indexOf(
        "Content-Security-Policy",
      ),
    ).toBeLessThan(isolatedHtml("<script>evil()</script>").indexOf("<script>"));
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

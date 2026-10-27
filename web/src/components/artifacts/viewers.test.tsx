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
  origin: "artifact",
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
  it("keeps links from navigating the frame; in-page anchors scroll", () => {
    document.body.innerHTML =
      '<a id="away" href="joueurs.html">Joueurs</a><a id="top" href="#target">Top</a>' +
      '<a id="js" href="javascript:location=\'/agents\'">JS</a>' +
      '<a id="stopper" href="/agents">Stopper</a><div id="target"></div>';
    document.getElementById("stopper")?.addEventListener("click", (e) => {
      e.stopPropagation();
    });
    const scroll = vi.fn();
    const target = document.getElementById("target");
    if (target) target.scrollIntoView = scroll;
    // The script the frame actually runs: guardLinks' source, as emitted.
    const emitted = /<script>([\s\S]*?)<\/script>/.exec(isolatedHtml("", []))?.[1] ?? "";
    new Function(emitted)();
    const click = (id: string) => {
      const event = new MouseEvent("click", { bubbles: true, cancelable: true });
      document.getElementById(id)?.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(click("away")).toBe(true);
    expect(click("top")).toBe(true);
    expect(click("js")).toBe(true);
    expect(click("stopper")).toBe(true);
    const middle = new MouseEvent("auxclick", { bubbles: true, cancelable: true, button: 1 });
    document.getElementById("away")?.dispatchEvent(middle);
    expect(middle.defaultPrevented).toBe(true);
    // A link inside an open shadow root.
    const host = document.createElement("div");
    document.body.append(host);
    const shadow = host.attachShadow({ mode: "open" });
    shadow.innerHTML = '<a href="joueurs.html"><span>Inside</span></a>';
    const inner = new MouseEvent("click", { bubbles: true, cancelable: true, composed: true });
    shadow.querySelector("span")?.dispatchEvent(inner);
    expect(inner.defaultPrevented).toBe(true);
    document.body.innerHTML = "";
    expect(scroll).toHaveBeenCalledOnce();
    const page = isolatedHtml("<p>authored</p>", []);
    expect(page.indexOf(")(document)</script>")).toBeLessThan(page.indexOf("<p>authored"));
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

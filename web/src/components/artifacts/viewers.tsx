"use client";

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType } from "react";
import Papa from "papaparse";
import { Streamdown } from "streamdown";
import { Loader2, Maximize, Pause, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Artifact } from "@/lib/api/resources/artifacts";

export interface ViewerProps {
  artifact: Artifact;
  bytes: ArrayBuffer;
}
export interface ViewerAdapter {
  id: string;
  supports: (mime: string) => boolean;
  component: ComponentType<ViewerProps>;
}
export function Loading({
  label,
  className,
}: {
  label: string;
  className?: string;
}) {
  return (
    <div
      role="status"
      className={cn(
        "flex h-full min-h-40 flex-col items-center justify-center gap-2.5 text-sm text-meta",
        className,
      )}
    >
      <Loader2 className="size-5 animate-spin text-petrol" />
      <span>{label}</span>
    </div>
  );
}
const PptxViewer = lazy(() => import("./pptx-viewer"));
const decode = (bytes: ArrayBuffer) => new TextDecoder().decode(bytes);

export function isolatedHtml(html: string): string {
  // Placed before all authored content. The frame has an opaque origin; no
  // network subresources, forms, nested frames or host API bridge are exposed.
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">${html}`;
}
// Even with connect-src 'none', a script can navigate its own frame to an
// outside URL carrying the page's text. Scripts are therefore opt-in per file.
const SCRIPTS_WARNING =
  "Scripts are off. Running them lets this page contact outside sites, including sending its own contents.";
const pill =
  "flex h-8 cursor-pointer items-center justify-center gap-1.5 rounded-full border border-border bg-white/90 text-[12px] font-semibold text-subtle shadow-[0_2px_8px_rgba(10,25,30,0.08)] backdrop-blur hover:bg-hover hover:text-ink";

function WebPageViewer({ bytes }: ViewerProps) {
  const box = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const [scripts, setScripts] = useState(false);
  return (
    // The toolbar hides in full screen; Esc exits.
    <div
      ref={box}
      className="relative h-full min-h-96 bg-white [&:fullscreen>div]:hidden"
    >
      <iframe
        // Remount on toggle: sandbox flags only apply to a fresh document.
        key={scripts ? "scripts" : "static"}
        ref={frame}
        title="HTML artifact"
        className="h-full w-full border-0 bg-white"
        sandbox={scripts ? "allow-scripts" : ""}
        referrerPolicy="no-referrer"
        srcDoc={isolatedHtml(decode(bytes))}
      />
      <div className="absolute right-3 top-3 flex gap-2">
        <button
          type="button"
          aria-pressed={scripts}
          title={scripts ? "Turn this page's scripts off" : SCRIPTS_WARNING}
          onClick={() => {
            setScripts((on) => !on);
          }}
          className={cn(pill, "px-3", scripts && "text-petrol")}
        >
          {scripts ? <Pause className="size-3" /> : <Play className="size-3" />}
          {scripts ? "Stop scripts" : "Run scripts"}
        </button>
        <button
          type="button"
          aria-label="Full screen"
          title="Full screen"
          onClick={() => {
            // Focus the page so its own keys (e.g. arrows in a deck) work.
            // Rejected when the browser or an embedding policy denies it: stay inline.
            box.current
              ?.requestFullscreen()
              .then(() => frame.current?.focus())
              .catch(() => undefined);
          }}
          className={cn(pill, "w-8")}
        >
          <Maximize className="size-3.5" />
        </button>
      </div>
    </div>
  );
}
function PdfViewer({ bytes }: ViewerProps) {
  const [url, setUrl] = useState<string>();
  useEffect(() => {
    const next = URL.createObjectURL(
      new Blob([bytes], { type: "application/pdf" }),
    );
    // URL lifetime is owned by this effect and cleaned up on replacement.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setUrl(next);
    return () => {
      URL.revokeObjectURL(next);
    };
  }, [bytes]);
  return url ? (
    <iframe title="PDF artifact" src={url} className="h-full min-h-96 w-full" />
  ) : null;
}
function MarkdownViewer({ bytes }: ViewerProps) {
  return (
    <div className="prose dark:prose-invert p-4">
      <Streamdown
        mode="static"
        allowedTags={{}}
        components={{ img: () => <span>[Image omitted]</span> }}
      >
        {decode(bytes)}
      </Streamdown>
    </div>
  );
}
function TextViewer({ bytes }: ViewerProps) {
  return (
    <pre className="whitespace-pre-wrap break-words p-4 text-sm">
      {decode(bytes)}
    </pre>
  );
}
function CsvViewer({ bytes }: ViewerProps) {
  const result = useMemo(
    () =>
      Papa.parse<string[]>(decode(bytes), {
        preview: 501,
        skipEmptyLines: true,
      }),
    [bytes],
  );
  const rows = result.data.slice(0, 500);
  return (
    <div className="overflow-auto p-3">
      <p className="mb-3 text-xs text-muted-foreground">
        Preview: up to 500 rows and 50 columns. Download for the complete file.
      </p>
      <table className="w-full border-collapse text-sm">
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.slice(0, 50).map((cell, j) => (
                <td
                  key={j}
                  className="max-w-80 truncate border p-2"
                  title={cell}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export const viewers: ViewerAdapter[] = [
  {
    id: "pptx",
    supports: (mime) =>
      mime ===
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    component: PptxViewer,
  },
  {
    id: "pdf",
    supports: (mime) => mime === "application/pdf",
    component: PdfViewer,
  },
  { id: "csv", supports: (mime) => mime === "text/csv", component: CsvViewer },
  {
    id: "markdown",
    supports: (mime) => mime === "text/markdown",
    component: MarkdownViewer,
  },
  {
    id: "html",
    supports: (mime) => mime === "text/html",
    component: WebPageViewer,
  },
  {
    id: "text",
    supports: (mime) => mime === "text/plain",
    component: TextViewer,
  },
];
export function ArtifactViewer(props: ViewerProps) {
  const Viewer = viewers.find((viewer) =>
    viewer.supports(props.artifact.mime_type),
  )?.component;
  return Viewer ? (
    <Suspense fallback={<Loading label="Loading viewer…" />}>
      <Viewer {...props} />
    </Suspense>
  ) : (
    <p className="p-4 text-sm">
      Preview unavailable for this file type. Download the original file to open
      it.
    </p>
  );
}

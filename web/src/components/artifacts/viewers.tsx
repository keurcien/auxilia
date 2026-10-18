"use client";

import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import type { ComponentType } from "react";
import Papa from "papaparse";
import { Streamdown } from "streamdown";
import { Loader2, Maximize } from "lucide-react";
import { cn } from "@/lib/utils";
import { getHtmlSources } from "@/lib/api/resources/artifacts";
import { CodeBlock } from "@/components/ai-elements/code-block";
import type { BundledLanguage } from "shiki";
import type { Artifact } from "@/lib/api/resources/artifacts";

export interface ViewerProps {
  artifact: Artifact;
  bytes: ArrayBuffer;
  /** Set when the viewer may save edits over the artifact. */
  onSave?: (bytes: Uint8Array) => Promise<void>;
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

export function isolatedHtml(html: string, sources: string[]): string {
  // Placed before all authored content. The frame has an opaque origin: no
  // cookies, auxilia API, forms, nested frames, fetch or host bridge. Scripts
  // run, and may load libraries, styles, fonts and images from the workspace's
  // allowed sources (ARTIFACT_HTML_SOURCES, validated by the backend).
  const remote = sources.map((source) => ` ${source}`).join("");
  return `<!doctype html><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'${remote}; style-src 'unsafe-inline'${remote}; img-src data: blob:${remote}; font-src data:${remote}; media-src data: blob:; connect-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">${html}`;
}
const pill =
  "flex h-8 cursor-pointer items-center justify-center gap-1.5 rounded-full border border-border bg-white/90 text-[12px] font-semibold text-subtle shadow-[0_2px_8px_rgba(10,25,30,0.08)] backdrop-blur hover:bg-hover hover:text-ink";

function WebPageViewer({ bytes }: ViewerProps) {
  const box = useRef<HTMLDivElement>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const [sources, setSources] = useState<string[]>();
  useEffect(() => {
    void getHtmlSources().then(setSources);
  }, []);
  if (!sources) return <Loading label="Loading page…" />;
  return (
    // The toolbar hides in full screen; Esc exits.
    <div
      ref={box}
      className="relative h-full min-h-96 bg-white [&:fullscreen>div]:hidden"
    >
      <iframe
        ref={frame}
        title="HTML artifact"
        className="h-full w-full border-0 bg-white"
        sandbox="allow-scripts"
        referrerPolicy="no-referrer"
        srcDoc={isolatedHtml(decode(bytes), sources)}
      />
      <div className="absolute right-3 top-3 flex gap-2">
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
const CODE_LANGUAGES: Record<string, BundledLanguage> = {
  "application/json": "json",
  "text/x-python": "python",
  "text/javascript": "javascript",
};
function CodeViewer({ artifact, bytes }: ViewerProps) {
  return (
    <CodeBlock
      code={decode(bytes)}
      language={CODE_LANGUAGES[artifact.mime_type]}
      showLineNumbers
      className="rounded-none"
    />
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
  {
    id: "code",
    supports: (mime) => mime in CODE_LANGUAGES,
    component: CodeViewer,
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

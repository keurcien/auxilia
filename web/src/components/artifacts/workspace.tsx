"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { CSSProperties, ReactNode, RefObject } from "react";
import Image from "next/image";
import { ChevronLeft, Download, FileText, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/app/(protected)/skills/lib/skill-form";
import { relativeTime } from "@/app/(protected)/skills/lib/relative-time";
import { ChatHeaderActions } from "@/components/layout/chat-header";
import { ArtifactViewer, Loading } from "./viewers";
import {
  contentUrl,
  listArtifacts,
  readArtifact,
  slidesExportUrl,
} from "@/lib/api/resources/artifacts";
import { getAuthProviders } from "@/lib/api/resources/auth";
import type { Artifact } from "@/lib/api/resources/artifacts";

const ArtifactContext = createContext<{
  items: Artifact[];
  selectedId?: string;
  open: (item: Artifact) => void;
}>({ items: [], open: () => {} });

// Label colour per file kind, on a document glyph with the extension on it.
function tone(mime: string): string {
  if (mime.includes("presentation")) return "#c2502f";
  if (mime === "text/csv" || mime.includes("spreadsheet")) return "#1e7a56";
  if (mime === "application/pdf") return "#b42318";
  if (mime === "text/html") return "#2a5c8a";
  if (mime.startsWith("image/")) return "#5b4bb0";
  if (mime.startsWith("text/")) return "#56646a";
  return "#8a9aa0";
}

function extension(item: Artifact): string {
  const dot = item.filename.lastIndexOf(".");
  return dot > 0 ? item.filename.slice(dot + 1).toUpperCase() : "FILE";
}

function meta(item: Artifact, withTime = false): string {
  const parts = [extension(item), formatBytes(item.size)];
  if (withTime && item.created_at) parts.push(relativeTime(item.created_at));
  return parts.join(" · ");
}

function FileTypeIcon({ item, large }: { item: Artifact; large?: boolean }) {
  const color = tone(item.mime_type);
  const label = extension(item).slice(0, 4);
  return (
    <svg
      aria-hidden
      viewBox="0 0 32 40"
      className={cn("flex-none font-mono", large ? "h-11 w-9" : "h-9 w-[29px]")}
    >
      <path
        d="M4 1.5h16.5L30.5 11.5V36a2.5 2.5 0 0 1-2.5 2.5H4A2.5 2.5 0 0 1 1.5 36V4A2.5 2.5 0 0 1 4 1.5z"
        fill="#fff"
        stroke="#dce4e4"
        strokeWidth="1.5"
      />
      <path
        d="M20.5 1.5v7.5a2.5 2.5 0 0 0 2.5 2.5h7.5"
        fill="#f1f5f5"
        stroke="#dce4e4"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <rect
        x="0"
        y="21"
        width={label.length > 3 ? 27 : 23}
        height="11"
        rx="2"
        fill={color}
      />
      <text
        x={label.length > 3 ? 13.5 : 11.5}
        y="29.2"
        textAnchor="middle"
        fontSize="7.2"
        fontWeight="600"
        fill="#fff"
      >
        {label}
      </text>
    </svg>
  );
}

const FIDELITY =
  "Preview may differ from the original. Download for full fidelity.";

function DownloadLink({ item, icon }: { item: Artifact; icon?: boolean }) {
  return icon ? (
    <a
      href={contentUrl(item)}
      download={item.filename}
      title="Download"
      aria-label={`Download ${item.title}`}
      onClick={(event) => {
        event.stopPropagation();
      }}
      className="flex size-[30px] flex-none items-center justify-center rounded-lg text-subtle hover:bg-hairline"
    >
      <Download className="size-3.5" />
    </a>
  ) : (
    <a
      href={contentUrl(item)}
      download={item.filename}
      title={FIDELITY}
      className="inline-flex flex-none items-center gap-1.5 rounded-lg bg-petrol px-3.5 py-2 text-[13px] font-semibold text-white hover:bg-petrol/90"
    >
      <Download className="size-3.5" />
      Download
    </a>
  );
}

const PPTX_MIME =
  "application/vnd.openxmlformats-officedocument.presentationml.presentation";

// Export to Slides rides on the Google sign-in client, so it only exists when
// the workspace has Google OAuth configured. Asked once per page load.
let googleEnabled: Promise<boolean> | undefined;

function useGoogleEnabled(): boolean {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    googleEnabled ??= getAuthProviders()
      .then((providers) => providers.google)
      .catch(() => false);
    void googleEnabled.then(setEnabled);
  }, []);
  return enabled;
}

function SlidesExportLink({ item }: { item: Artifact }) {
  const enabled = useGoogleEnabled();
  if (!enabled) return null;
  return (
    <a
      href={slidesExportUrl(item)}
      target="_blank"
      rel="noopener noreferrer"
      title="Open a copy in Google Slides"
      aria-label={`Open ${item.title} in Google Slides`}
      className="inline-flex flex-none items-center gap-1.5 rounded-lg border border-hairline px-3.5 py-2 text-[13px] font-semibold text-ink hover:bg-hairline @max-[440px]/panel:px-2.5"
    >
      <Image
        unoptimized
        src="https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/slides.png"
        alt=""
        width={14}
        height={14}
        className="size-3.5 object-contain"
      />
      {/* Logo only on a narrow panel, so the header keeps its close button. */}
      <span className="@max-[440px]/panel:hidden">Google Slides</span>
    </a>
  );
}

export function ArtifactCards({ toolCallId }: { toolCallId: string }) {
  const { items, selectedId, open } = useContext(ArtifactContext);
  return items
    .filter((item) => item.tool_call_id === toolCallId)
    .map((item) => (
      <button
        key={item.id}
        type="button"
        onClick={() => {
          open(item);
        }}
        className={cn(
          "my-2 flex w-full max-w-md items-center gap-3 rounded-xl border p-2.5 text-left transition-colors",
          selectedId === item.id
            ? "border-petrol bg-petrol-tint"
            : "border-border hover:bg-hover",
        )}
      >
        <FileTypeIcon item={item} />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-[13.5px] font-bold">{item.title}</span>
          <span className="font-mono text-[11px] text-label">{meta(item)}</span>
        </span>
        <span className="flex-none rounded-full bg-petrol-chip px-2 py-1 text-[11px] font-semibold text-petrol">
          Open
        </span>
      </button>
    ));
}

function Preview({ artifact }: { artifact: Artifact }) {
  const [bytes, setBytes] = useState<ArrayBuffer>();
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void readArtifact(artifact, controller.signal)
      .then(setBytes)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Could not open file.",
          );
      });
    return () => {
      controller.abort();
    };
  }, [artifact, attempt]);
  if (error)
    return (
      <div
        role="alert"
        className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm text-subtle"
      >
        <p>{error}</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            setError(undefined);
            setAttempt((x) => x + 1);
          }}
        >
          Retry
        </Button>
      </div>
    );
  return bytes ? (
    <ArtifactViewer artifact={artifact} bytes={bytes} />
  ) : (
    <Loading label="Loading file…" />
  );
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      aria-label="Close artifact viewer"
      onClick={onClose}
      className="flex size-8 flex-none items-center justify-center rounded-lg text-subtle hover:bg-hover"
    >
      <X className="size-3.5" />
    </button>
  );
}

function FileList({
  items,
  onOpen,
  onClose,
}: {
  items: Artifact[];
  onOpen: (item: Artifact) => void;
  onClose: () => void;
}) {
  return (
    <>
      <header className="flex items-center gap-2.5 border-b border-hairline py-3 pl-5 pr-3">
        <h2 className="text-[14.5px] font-bold">Files in this thread</h2>
        <span className="flex-1 font-mono text-[11px] text-label">
          {items.length}
        </span>
        <CloseButton onClose={onClose} />
      </header>
      <ul className="min-h-0 flex-1 overflow-auto p-2.5">
        {items.map((item) => (
          <li key={item.id}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => {
                onOpen(item);
              }}
              onKeyDown={(event) => {
                // Keys on the nested download link belong to the link.
                if (event.target !== event.currentTarget) return;
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onOpen(item);
                }
              }}
              className="flex cursor-pointer items-center gap-3.5 rounded-[10px] px-3 py-2.5 hover:bg-hover"
            >
              <FileTypeIcon item={item} large />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate text-[13.5px] font-bold">
                  {item.title}
                </span>
                <span className="truncate font-mono text-[11px] text-label">
                  {meta(item, true)}
                </span>
              </span>
              <DownloadLink item={item} icon />
            </div>
          </li>
        ))}
      </ul>
      {items.some((item) => item.temporary) && (
        <p className="flex items-center gap-1.5 border-t border-hairline px-5 py-2.5 text-[11.5px] text-label">
          <span className="size-1.5 rounded-full bg-warning" />
          Files are temporary — download the ones you want to keep.
        </p>
      )}
    </>
  );
}

const MIN_PANEL = 320;
const MIN_CHAT = 360;

function ResizeHandle({
  container,
  width,
  onResize,
}: {
  container: RefObject<HTMLDivElement | null>;
  width?: number;
  onResize: (width: number) => void;
}) {
  const resize = (next: number) => {
    const total = container.current?.getBoundingClientRect().width ?? 0;
    onResize(Math.round(Math.min(Math.max(next, MIN_PANEL), total - MIN_CHAT)));
  };
  const current = () =>
    width ?? (container.current?.getBoundingClientRect().width ?? 0) / 2;
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize file panel"
      aria-valuenow={Math.round(current())}
      tabIndex={0}
      onPointerDown={(event) => {
        // Capture keeps the drag alive over iframes (PDF/HTML previews).
        event.currentTarget.setPointerCapture(event.pointerId);
        document.body.style.userSelect = "none";
      }}
      onPointerMove={(event) => {
        if (!event.currentTarget.hasPointerCapture(event.pointerId)) return;
        const right = container.current?.getBoundingClientRect().right ?? 0;
        resize(right - event.clientX);
      }}
      onPointerUp={() => {
        document.body.style.userSelect = "";
      }}
      onLostPointerCapture={() => {
        document.body.style.userSelect = "";
      }}
      onKeyDown={(event) => {
        if (event.key === "ArrowLeft") resize(current() + 32);
        if (event.key === "ArrowRight") resize(current() - 32);
      }}
      className="group absolute inset-y-0 -left-1.5 z-10 hidden w-3 cursor-col-resize touch-none @min-[680px]/ws:block"
    >
      <span className="absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors group-hover:w-0.5 group-hover:bg-petrol group-focus-visible:w-0.5 group-focus-visible:bg-petrol group-active:w-0.5 group-active:bg-petrol" />
    </div>
  );
}

export function ArtifactWorkspace({
  threadId,
  running,
  refreshKey,
  children,
}: {
  threadId: string;
  running: boolean;
  refreshKey: string;
  children: ReactNode;
}) {
  const [items, setItems] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<Artifact>();
  const [listOpen, setListOpen] = useState(false);
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const known = useRef<Set<string> | null>(null);
  const container = useRef<HTMLDivElement>(null);
  // One width for list and previewer, so switching views never jumps.
  const [width, setWidth] = useState<number>();
  const open = useCallback((item: Artifact) => {
    setListOpen(false);
    setSelected(item);
  }, []);
  const close = () => {
    setListOpen(false);
    setSelected(undefined);
  };
  useEffect(() => {
    const controller = new AbortController();
    let fetching = false;
    const refresh = async () => {
      if (fetching) return;
      fetching = true;
      try {
        const next = await listArtifacts(threadId, controller.signal);
        if (controller.signal.aborted) return;
        const fresh =
          known.current === null
            ? []
            : next.filter((item) => !known.current?.has(item.id));
        known.current = new Set(next.map((item) => item.id));
        setItems(next);
        setError(undefined);
        if (fresh.length) setSelected(fresh[fresh.length - 1]);
      } catch (cause) {
        if (!controller.signal.aborted)
          setError(
            cause instanceof Error ? cause.message : "Could not load files.",
          );
      } finally {
        fetching = false;
      }
    };
    void refresh();
    const timer = running
      ? setInterval(() => {
          void refresh();
        }, 3000)
      : undefined;
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [threadId, running, refreshKey, attempt]);
  const newestFirst = [...items].reverse();
  const position = selected
    ? newestFirst.findIndex((item) => item.id === selected.id)
    : -1;
  return (
    <ArtifactContext.Provider value={{ items, selectedId: selected?.id, open }}>
      {/* Side by side only once both minimums fit (MIN_PANEL + MIN_CHAT); overlay below. */}
      <div
        ref={container}
        className="@container/ws relative flex h-full min-w-0"
      >
        <div className="relative flex min-w-0 flex-1 flex-col">
          {(items.length > 0 || error) && (
            <ChatHeaderActions>
              {/* A failed poll keeps already-loaded files reachable; the next
                  successful poll clears the error. */}
              {error && items.length === 0 ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-[30px] rounded-full"
                  onClick={() => {
                    setAttempt((x) => x + 1);
                  }}
                >
                  Retry loading files
                </Button>
              ) : (
                <button
                  type="button"
                  aria-pressed={listOpen && !selected}
                  onClick={() => {
                    const showing = listOpen && !selected;
                    setSelected(undefined);
                    setListOpen(!showing);
                  }}
                  className="flex h-[30px] cursor-pointer items-center gap-1.5 rounded-full bg-petrol-chip px-3 text-[12.5px] font-semibold text-petrol hover:bg-petrol-tint aria-pressed:ring-1 aria-pressed:ring-petrol/40"
                >
                  <FileText className="size-3.5" />
                  Files
                  <span className="font-mono text-[11px]">{items.length}</span>
                </button>
              )}
            </ChatHeaderActions>
          )}
          <div className="min-h-0 flex-1">{children}</div>
        </div>
        {(selected ?? listOpen) && (
          <aside
            aria-label="Artifact viewer"
            style={
              { "--panel-w": width ? `${width}px` : "50%" } as CSSProperties
            }
            className="@container/panel absolute inset-0 z-30 flex min-w-0 flex-col border-l border-hairline bg-background @min-[680px]/ws:relative @min-[680px]/ws:inset-auto @min-[680px]/ws:w-[var(--panel-w)] @min-[680px]/ws:min-w-80 @min-[680px]/ws:max-w-[calc(100%-22.5rem)] @min-[680px]/ws:flex-none"
          >
            <ResizeHandle
              container={container}
              width={width}
              onResize={setWidth}
            />
            {selected ? (
              <>
                <header className="flex items-center gap-2.5 border-b border-hairline py-3 pl-3 pr-3">
                  {listOpen ? (
                    <button
                      type="button"
                      aria-label="Back to files"
                      onClick={() => {
                        setSelected(undefined);
                      }}
                      className="flex size-[30px] flex-none items-center justify-center rounded-lg bg-hover text-ink"
                    >
                      <ChevronLeft className="size-3.5" />
                    </button>
                  ) : (
                    <span className="w-2" />
                  )}
                  <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <h2 className="truncate text-[14.5px] font-bold">
                      {selected.title}
                    </h2>
                    <p className="truncate font-mono text-[11px] text-label">
                      {meta(selected)}
                      {listOpen &&
                        position >= 0 &&
                        ` · ${position + 1} of ${items.length} files`}
                      {selected.temporary && (
                        <>
                          {" · "}
                          <span className="text-warning">
                            temporary — download to keep
                          </span>
                        </>
                      )}
                    </p>
                  </div>
                  {selected.mime_type === PPTX_MIME && (
                    <SlidesExportLink item={selected} />
                  )}
                  <DownloadLink item={selected} />
                  <CloseButton onClose={close} />
                </header>
                <div className="min-h-0 flex-1 overflow-auto">
                  <Preview key={selected.id} artifact={selected} />
                </div>
              </>
            ) : (
              <FileList
                items={newestFirst}
                onOpen={setSelected}
                onClose={close}
              />
            )}
          </aside>
        )}
      </div>
    </ArtifactContext.Provider>
  );
}

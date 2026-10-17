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
import { ChevronLeft, Download, ExternalLink, FileText, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/app/(protected)/skills/lib/skill-form";
import { relativeTime } from "@/app/(protected)/skills/lib/relative-time";
import { ChatHeaderActions } from "@/components/layout/chat-header";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";
import { McpAppWidget } from "@/app/(protected)/agents/[id]/chat/components/mcp-app-widget";
import type { DisplayedApp } from "@/app/(protected)/agents/[id]/chat/components/mcp-app-widget";
import { ArtifactViewer, Loading } from "./viewers";
import {
  contentUrl,
  listArtifacts,
  readArtifact,
  saveArtifact,
  slidesExportUrl,
} from "@/lib/api/resources/artifacts";
import { getAuthProviders } from "@/lib/api/resources/auth";
import type { Artifact } from "@/lib/api/resources/artifacts";

// MCP apps are thread outputs too: inline by default, and while one is open in
// the panel (the MCP Apps `fullscreen` display mode) its inline spot is a card.
const ArtifactContext = createContext<{
  items: Artifact[];
  selectedId?: string;
  open: (item: Artifact) => void;
  openAppId?: string;
  openApp: (toolCallId: string) => void;
  registerApp: (toolCallId: string, app: SlotApp) => void;
  unregisterApp: (toolCallId: string) => void;
}>({
  items: [],
  open: () => {},
  openApp: () => {},
  registerApp: () => {},
  unregisterApp: () => {},
});

type Entry =
  | { kind: "file"; key: string; toolCallId: string; item: Artifact }
  | { kind: "app"; key: string; toolCallId: string; app: SlotApp };

/** An app plus the MCP server it comes from, which identifies it in the UI. */
type SlotApp = DisplayedApp & { serverName: string; serverIcon?: string };

function widgetProps(app: SlotApp): DisplayedApp {
  const { input, output, structuredContent, errorText, toolName, appToolInfo } =
    app;
  return { input, output, structuredContent, errorText, toolName, appToolInfo };
}

function appTitle(app: DisplayedApp): string {
  return humanizeToolName(app.toolName);
}

function sameApp(a: SlotApp, b: SlotApp): boolean {
  return (
    a.serverName === b.serverName &&
    a.serverIcon === b.serverIcon &&
    a.input === b.input &&
    a.output === b.output &&
    a.structuredContent === b.structuredContent &&
    a.errorText === b.errorText &&
    a.toolName === b.toolName &&
    a.appToolInfo.resourceUri === b.appToolInfo.resourceUri &&
    a.appToolInfo.serverId === b.appToolInfo.serverId
  );
}

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

function FileTypeIcon({
  label: text,
  color,
  large,
}: {
  label: string;
  color: string;
  large?: boolean;
}) {
  const label = text.slice(0, 4);
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

function ArtifactIcon({ entry, large }: { entry: Entry; large?: boolean }) {
  if (entry.kind === "file")
    return (
      <FileTypeIcon
        label={extension(entry.item)}
        color={tone(entry.item.mime_type)}
        large={large}
      />
    );
  // The server's logo, as on the tool steps: an app reads as "from Metabase".
  const { serverName, serverIcon } = entry.app;
  return (
    <span
      aria-hidden
      className={cn(
        "flex flex-none items-center justify-center rounded-lg border border-border bg-card",
        large ? "size-11" : "size-9",
      )}
    >
      {serverIcon ? (
        <Image
          unoptimized
          src={serverIcon}
          alt=""
          width={large ? 22 : 18}
          height={large ? 22 : 18}
          className="rounded-[3px] object-contain"
        />
      ) : (
        <span className="text-[13px] font-bold text-label">
          {serverName.charAt(0).toUpperCase()}
        </span>
      )}
    </span>
  );
}

function entryTitle(entry: Entry): string {
  return entry.kind === "file" ? entry.item.title : appTitle(entry.app);
}

function entryMeta(entry: Entry, withTime = false): string {
  return entry.kind === "file" ? meta(entry.item, withTime) : entry.app.serverName;
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

function Card({
  entry,
  selected,
  onOpen,
}: {
  entry: Entry;
  selected: boolean;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onOpen}
      className={cn(
        "my-2 flex w-full max-w-md items-center gap-3 rounded-xl border p-2.5 text-left transition-colors",
        selected ? "border-petrol bg-petrol-tint" : "border-border hover:bg-hover",
      )}
    >
      <ArtifactIcon entry={entry} />
      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="truncate text-[13.5px] font-bold">
          {entryTitle(entry)}
        </span>
        <span className="font-mono text-[11px] text-label">
          {entryMeta(entry)}
        </span>
      </span>
      <span className="flex-none rounded-full bg-petrol-chip px-2 py-1 text-[11px] font-semibold text-petrol">
        Open
      </span>
    </button>
  );
}

export function ArtifactCards({ toolCallId }: { toolCallId: string }) {
  const { items, selectedId, open } = useContext(ArtifactContext);
  return items
    .filter((item) => item.tool_call_id === toolCallId)
    .map((item) => (
      <Card
        key={item.id}
        entry={{ kind: "file", key: item.id, toolCallId, item }}
        selected={selectedId === item.id}
        onOpen={() => {
          open(item);
        }}
      />
    ));
}

/** An MCP app in the transcript: live inline, or a card while it is open in
 *  the panel, so exactly one copy of the app runs at a time. */
export function AppSlot({
  toolCallId,
  app,
}: {
  toolCallId: string;
  app: SlotApp;
}) {
  const { openAppId, openApp, registerApp, unregisterApp } =
    useContext(ArtifactContext);
  useEffect(() => {
    registerApp(toolCallId, app);
  }, [registerApp, toolCallId, app]);
  useEffect(
    () => () => {
      unregisterApp(toolCallId);
    },
    [unregisterApp, toolCallId],
  );
  const title = appTitle(app);
  if (openAppId === toolCallId)
    return (
      <Card
        entry={{ kind: "app", key: toolCallId, toolCallId, app }}
        selected
        onOpen={() => {
          openApp(toolCallId);
        }}
      />
    );
  return (
    <div className="mt-2 w-full min-w-0 overflow-hidden rounded-xl border border-border">
      <div className="flex items-center gap-2 border-b border-hairline py-1 pl-3 pr-1">
        <span className="min-w-0 flex-1 truncate text-[12.5px] font-semibold text-label">
          {title}
        </span>
        <button
          type="button"
          title="Open in panel"
          aria-label={`Open ${title} in panel`}
          onClick={() => {
            openApp(toolCallId);
          }}
          className="flex size-7 flex-none items-center justify-center rounded-lg text-subtle hover:bg-hover"
        >
          <ExternalLink className="size-3.5" />
        </button>
      </div>
      <McpAppWidget
        {...widgetProps(app)}
        className="mt-0"
        onRequestDisplayMode={(mode) => {
          if (mode !== "fullscreen") return "inline";
          openApp(toolCallId);
          return "fullscreen";
        }}
      />
    </div>
  );
}

function Preview({
  artifact,
  onSave,
}: {
  artifact: Artifact;
  onSave?: (bytes: Uint8Array) => Promise<void>;
}) {
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
    <ArtifactViewer artifact={artifact} bytes={bytes} onSave={onSave} />
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
  entries,
  onOpen,
  onClose,
}: {
  entries: Entry[];
  onOpen: (entry: Entry) => void;
  onClose: () => void;
}) {
  return (
    <>
      <header className="flex items-center gap-2.5 border-b border-hairline py-3 pl-5 pr-3">
        <h2 className="text-[14.5px] font-bold">Artifacts in this thread</h2>
        <span className="flex-1 font-mono text-[11px] text-label">
          {entries.length}
        </span>
        <CloseButton onClose={onClose} />
      </header>
      <ul className="min-h-0 flex-1 overflow-auto p-2.5">
        {entries.map((entry) => (
          <li key={entry.key}>
            <div
              role="button"
              tabIndex={0}
              onClick={() => {
                onOpen(entry);
              }}
              onKeyDown={(event) => {
                // Keys on the nested download link belong to the link.
                if (event.target !== event.currentTarget) return;
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onOpen(entry);
                }
              }}
              className="flex cursor-pointer items-center gap-3.5 rounded-[10px] px-3 py-2.5 hover:bg-hover"
            >
              <ArtifactIcon entry={entry} large />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate text-[13.5px] font-bold">
                  {entryTitle(entry)}
                </span>
                <span className="truncate font-mono text-[11px] text-label">
                  {entryMeta(entry, true)}
                </span>
              </span>
              {entry.kind === "file" && <DownloadLink item={entry.item} icon />}
            </div>
          </li>
        ))}
      </ul>
      {entries.some((entry) => entry.kind === "file" && entry.item.temporary) && (
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
  editable = false,
  refreshKey,
  order = [],
  children,
}: {
  threadId: string;
  running: boolean;
  /** The viewer owns the thread: presentations can be edited between turns. */
  editable?: boolean;
  refreshKey: string;
  /** Tool-call ids in transcript order: files and apps are listed by it. */
  order?: string[];
  children: ReactNode;
}) {
  const [items, setItems] = useState<Artifact[]>([]);
  const [selected, setSelected] = useState<Artifact>();
  // Mutually exclusive with `selected`: the panel shows a file or an app.
  const [openAppId, setOpenAppId] = useState<string>();
  const [apps, setApps] = useState<ReadonlyMap<string, SlotApp>>(
    () => new Map(),
  );
  // Set when the user chose what the panel shows: auto-open never replaces it.
  const userPicked = useRef(false);
  const [listOpen, setListOpen] = useState(false);
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  // Artifact id → sha256: an agent update in place shows like a new file.
  const known = useRef<Map<string, string> | null>(null);
  const container = useRef<HTMLDivElement>(null);
  // One width for list and previewer, so switching views never jumps.
  const [width, setWidth] = useState<number>();
  const open = useCallback((item: Artifact) => {
    userPicked.current = true;
    setListOpen(false);
    setOpenAppId(undefined);
    setSelected(item);
  }, []);
  const openApp = useCallback((toolCallId: string) => {
    userPicked.current = true;
    setListOpen(false);
    setSelected(undefined);
    setOpenAppId(toolCallId);
  }, []);
  const registerApp = useCallback((toolCallId: string, app: SlotApp) => {
    setApps((prev) => {
      const known = prev.get(toolCallId);
      return known && sameApp(known, app)
        ? prev
        : new Map(prev).set(toolCallId, app);
    });
  }, []);
  const unregisterApp = useCallback((toolCallId: string) => {
    setApps((prev) => {
      if (!prev.has(toolCallId)) return prev;
      const next = new Map(prev);
      next.delete(toolCallId);
      return next;
    });
  }, []);
  const close = () => {
    userPicked.current = false;
    setListOpen(false);
    setSelected(undefined);
    setOpenAppId(undefined);
  };
  // From the list: keeps `listOpen`, so the header offers a way back.
  const pick = (entry: Entry) => {
    userPicked.current = true;
    setSelected(entry.kind === "file" ? entry.item : undefined);
    setOpenAppId(entry.kind === "app" ? entry.key : undefined);
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
            : next.filter(
                (item) => known.current?.get(item.id) !== item.sha256,
              );
        known.current = new Map(next.map((item) => [item.id, item.sha256]));
        setItems(next);
        // The open file follows its updates (the viewer reloads on a new sha).
        // An unchanged poll keeps the same object: Preview refetches on identity.
        setSelected((prev) => {
          const match = prev && next.find((item) => item.id === prev.id);
          return match && JSON.stringify(match) !== JSON.stringify(prev)
            ? match
            : prev;
        });
        setError(undefined);
        if (fresh.length && !userPicked.current) {
          setOpenAppId(undefined);
          setSelected(fresh[fresh.length - 1]);
        }
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
  const app = openAppId ? apps.get(openAppId) : undefined;
  const entries: Entry[] = [
    ...items.map((item): Entry => ({
      kind: "file",
      key: item.id,
      toolCallId: item.tool_call_id,
      item,
    })),
    ...Array.from(apps, ([toolCallId, app]): Entry => ({
      kind: "app",
      key: toolCallId,
      toolCallId,
      app,
    })),
  ];
  // Newest first by transcript position; a call missing from the root
  // transcript (a subagent's file) counts as newest.
  const rank = (entry: Entry) => {
    const index = order.indexOf(entry.toolCallId);
    return index < 0 ? Infinity : index;
  };
  const newestFirst = entries
    .reverse()
    .sort((a, b) => (rank(a) === rank(b) ? 0 : rank(b) - rank(a)));
  const currentKey = selected?.id ?? (app ? openAppId : undefined);
  const position = currentKey
    ? newestFirst.findIndex((entry) => entry.key === currentKey)
    : -1;
  return (
    <ArtifactContext.Provider
      value={{
        items,
        selectedId: selected?.id,
        open,
        openAppId,
        openApp,
        registerApp,
        unregisterApp,
      }}
    >
      {/* Side by side only once both minimums fit (MIN_PANEL + MIN_CHAT); overlay below. */}
      <div
        ref={container}
        className="@container/ws relative flex h-full min-w-0"
      >
        <div className="relative flex min-w-0 flex-1 flex-col">
          {(entries.length > 0 || error) && (
            <ChatHeaderActions>
              {/* A failed poll keeps already-loaded files reachable; the next
                  successful poll clears the error. */}
              {error && entries.length === 0 ? (
                <Button
                  variant="outline"
                  size="sm"
                  className="h-[30px] rounded-full"
                  onClick={() => {
                    setAttempt((x) => x + 1);
                  }}
                >
                  Retry loading artifacts
                </Button>
              ) : (
                <button
                  type="button"
                  aria-pressed={listOpen && !currentKey}
                  onClick={() => {
                    const showing = listOpen && !currentKey;
                    // An open list is the user's pick too: no auto-open over it.
                    userPicked.current = !showing;
                    setSelected(undefined);
                    setOpenAppId(undefined);
                    setListOpen(!showing);
                  }}
                  className="flex h-[30px] cursor-pointer items-center gap-1.5 rounded-full bg-petrol-chip px-3 text-[12.5px] font-semibold text-petrol hover:bg-petrol-tint aria-pressed:ring-1 aria-pressed:ring-petrol/40"
                >
                  <FileText className="size-3.5" />
                  Artifacts
                  <span className="font-mono text-[11px]">{entries.length}</span>
                </button>
              )}
            </ChatHeaderActions>
          )}
          <div className="min-h-0 flex-1">{children}</div>
        </div>
        {(selected || app || listOpen) && (
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
            {selected || app ? (
              <>
                <header className="flex items-center gap-2.5 border-b border-hairline py-3 pl-3 pr-3">
                  {listOpen ? (
                    <button
                      type="button"
                      aria-label="Back to artifacts"
                      onClick={() => {
                        setSelected(undefined);
                        setOpenAppId(undefined);
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
                      {selected ? selected.title : app && appTitle(app)}
                    </h2>
                    <p className="truncate font-mono text-[11px] text-label">
                      {selected ? meta(selected) : app?.serverName}
                      {listOpen &&
                        position >= 0 &&
                        ` · ${position + 1} of ${newestFirst.length} artifacts`}
                      {selected?.temporary && (
                        <>
                          {" · "}
                          <span className="text-warning">
                            temporary — download to keep
                          </span>
                        </>
                      )}
                    </p>
                  </div>
                  {selected?.mime_type === PPTX_MIME && (
                    <SlidesExportLink item={selected} />
                  )}
                  {selected && <DownloadLink item={selected} />}
                  <CloseButton onClose={close} />
                </header>
                {selected ? (
                  <div className="min-h-0 flex-1 overflow-auto">
                    <Preview
                      key={`${selected.id}:${selected.sha256}`}
                      artifact={selected}
                      onSave={
                        editable && !running && selected.mime_type === PPTX_MIME
                          ? async (bytes) => {
                              const saved = await saveArtifact(selected, bytes);
                              known.current?.set(saved.id, saved.sha256);
                              setItems((prev) =>
                                prev.map((item) =>
                                  item.id === saved.id ? saved : item,
                                ),
                              );
                              // Only if the panel still shows what was saved:
                              // the user may have closed it or opened another file.
                              setSelected((current) =>
                                current?.id === saved.id &&
                                current.sha256 === selected.sha256
                                  ? saved
                                  : current,
                              );
                            }
                          : undefined
                      }
                    />
                  </div>
                ) : (
                  app && (
                    <div className="flex min-h-0 flex-1 flex-col">
                      <McpAppWidget
                        key={openAppId}
                        {...widgetProps(app)}
                        displayMode="fullscreen"
                        onRequestDisplayMode={(mode) => {
                          if (mode !== "inline") return "fullscreen";
                          close();
                          return "inline";
                        }}
                      />
                    </div>
                  )
                )}
              </>
            ) : (
              <FileList
                entries={newestFirst}
                onOpen={pick}
                onClose={close}
              />
            )}
          </aside>
        )}
      </div>
    </ArtifactContext.Provider>
  );
}

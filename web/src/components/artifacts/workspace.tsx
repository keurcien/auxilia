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
import {
  Check,
  ChevronLeft,
  Copy,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { formatBytes } from "@/app/(protected)/skills/lib/skill-form";
import { relativeTime } from "@/app/(protected)/skills/lib/relative-time";
import { ChatHeaderActions, HeaderTip } from "@/components/layout/chat-header";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";
import { McpAppWidget } from "@/app/(protected)/agents/[id]/chat/components/mcp-app-widget";
import type { DisplayedApp } from "@/app/(protected)/agents/[id]/chat/components/mcp-app-widget";
import { ArtifactViewer, decodeArtifactText, Loading } from "./viewers";
import { FileTypeIcon, extension, tone } from "./file-type-icon";
import {
  ArtifactConflictError,
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

function meta(item: Artifact, withTime = false): string {
  const parts = [extension(item.filename), formatBytes(item.size)];
  if (withTime && item.created_at) parts.push(relativeTime(item.created_at));
  return parts.join(" / ");
}

function ArtifactIcon({ entry, large }: { entry: Entry; large?: boolean }) {
  if (entry.kind === "file")
    return (
      <FileTypeIcon
        label={extension(entry.item.filename)}
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

const COPYABLE_APPLICATION_MIMES = new Set([
  "application/graphql",
  "application/javascript",
  "application/json",
  "application/ld+json",
  "application/sql",
  "application/toml",
  "application/xml",
  "application/x-httpd-php",
  "application/x-javascript",
  "application/x-ndjson",
  "application/x-sh",
  "application/x-toml",
  "application/x-yaml",
  "application/yaml",
]);

function canCopyContent(item: Artifact): boolean {
  const mime = item.mime_type.toLowerCase().split(";", 1)[0];
  return mime.startsWith("text/") || COPYABLE_APPLICATION_MIMES.has(mime);
}

function CopyArtifactButton({ item }: { item: Artifact }) {
  const [status, setStatus] = useState<"idle" | "copying" | "copied">("idle");
  const resetTimer = useRef<number | undefined>(undefined);

  useEffect(
    () => () => {
      window.clearTimeout(resetTimer.current);
    },
    [],
  );

  const copy = async () => {
    if (status === "copying") return;
    setStatus("copying");
    try {
      const bytes = await readArtifact(item, new AbortController().signal);
      const clipboard = navigator.clipboard as Clipboard | undefined;
      if (!clipboard) throw new Error("Clipboard unavailable");
      await clipboard.writeText(decodeArtifactText(bytes));
      setStatus("copied");
      window.clearTimeout(resetTimer.current);
      resetTimer.current = window.setTimeout(() => {
        setStatus("idle");
      }, 1600);
    } catch {
      setStatus("idle");
      toast.error("Could not copy the artifact content");
    }
  };

  const copied = status === "copied";
  return (
    <button
      type="button"
      aria-label={copied ? "Artifact content copied" : "Copy artifact content"}
      title={copied ? "Copied" : "Copy content"}
      disabled={status === "copying"}
      onClick={() => {
        void copy();
      }}
      className="flex size-8 flex-none cursor-pointer items-center justify-center rounded-lg border border-hairline text-subtle transition-colors hover:bg-hover hover:text-ink disabled:cursor-wait"
    >
      {status === "copying" ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : copied ? (
        <Check className="size-3.5 text-petrol" />
      ) : (
        <Copy className="size-3.5" />
      )}
    </button>
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
        selected
          ? "border-petrol bg-petrol-tint dark:border-panel-terminal/35 dark:bg-panel-terminal/10"
          : "border-border hover:bg-hover dark:bg-transparent dark:hover:bg-white/5",
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
      <span className="flex-none rounded-full bg-petrol-chip px-2 py-1 text-[11px] font-semibold text-petrol dark:bg-panel-terminal/10 dark:text-panel-terminal">
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

/** Resolve attachment references on human messages against the thread files. */
export function useAttachedFiles(ids: string[]): Artifact[] {
  const { items } = useContext(ArtifactContext);
  const byId = new Map(
    items
      .filter((item) => item.origin === "attachment")
      .map((item) => [item.id, item]),
  );
  return ids.flatMap((id) => {
    const item = byId.get(id);
    return item ? [item] : [];
  });
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
              className="flex cursor-pointer items-center gap-3.5 rounded-[10px] px-3 py-2.5 hover:bg-hover dark:hover:bg-white/5"
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
          Files are temporary. Download the ones you want to keep.
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
                (item) =>
                  item.origin === "artifact" &&
                  known.current?.get(item.id) !== item.sha256,
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
    ...items
      .filter(
        (item): item is Artifact & { tool_call_id: string } =>
          item.origin === "artifact" && item.tool_call_id !== null,
      )
      .map((item): Entry => ({
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
                <HeaderTip
                  label="Artifacts"
                  hint={`${entries.length} ${entries.length === 1 ? "artifact" : "artifacts"} in this thread`}
                >
                  <button
                    type="button"
                    aria-label={`Artifacts (${entries.length})`}
                    aria-pressed={listOpen && !currentKey}
                    onClick={() => {
                      const showing = listOpen && !currentKey;
                      // An open list is the user's pick too: no auto-open over it.
                      userPicked.current = !showing;
                      setSelected(undefined);
                      setOpenAppId(undefined);
                      setListOpen(!showing);
                    }}
                    className="relative flex size-[30px] cursor-pointer items-center justify-center rounded-full border border-transparent bg-petrol-chip text-petrol hover:bg-petrol-tint aria-pressed:ring-1 aria-pressed:ring-petrol/40 dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal dark:hover:bg-panel-terminal/15"
                  >
                    <FileText className="size-3.5" />
                    <span className="absolute -right-1 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-petrol px-1 font-mono text-[9.5px] font-semibold leading-none text-white ring-2 ring-background dark:bg-panel-terminal dark:text-ink">
                      {entries.length}
                    </span>
                  </button>
                </HeaderTip>
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
                        ` / ${position + 1} of ${newestFirst.length} artifacts`}
                      {selected?.temporary && (
                        <>
                          {" / "}
                          <span className="text-warning">
                            temporary: download to keep
                          </span>
                        </>
                      )}
                    </p>
                  </div>
                  {selected && canCopyContent(selected) && (
                    <CopyArtifactButton
                      key={`${selected.id}:${selected.sha256}`}
                      item={selected}
                    />
                  )}
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
                              try {
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
                              } catch (cause) {
                                if (cause instanceof ArtifactConflictError) {
                                  const latest = await listArtifacts(
                                    threadId,
                                    new AbortController().signal,
                                  );
                                  known.current = new Map(
                                    latest.map((item) => [item.id, item.sha256]),
                                  );
                                  setItems(latest);
                                  setSelected(
                                    latest.find((item) => item.id === selected.id),
                                  );
                                }
                                throw cause;
                              }
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

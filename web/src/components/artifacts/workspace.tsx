"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { FileText, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ArtifactViewer } from "./viewers";
import {
  contentUrl,
  listArtifacts,
  readArtifact,
} from "@/lib/api/resources/artifacts";
import type { Artifact } from "@/lib/api/resources/artifacts";

const ArtifactContext = createContext<{
  items: Artifact[];
  open: (item: Artifact) => void;
}>({ items: [], open: () => {} });

export function ArtifactCards({ toolCallId }: { toolCallId: string }) {
  const { items, open } = useContext(ArtifactContext);
  return items
    .filter((item) => item.tool_call_id === toolCallId)
    .map((item) => (
      <Button
        key={item.id}
        variant="outline"
        className="my-2 mr-2 max-w-full"
        onClick={() => {
          open(item);
        }}
      >
        <FileText className="size-4 shrink-0" />
        <span className="truncate">{item.title}</span>
        {item.temporary && (
          <span className="text-xs text-muted-foreground">Temporary</span>
        )}
      </Button>
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
      <div role="alert" className="p-4">
        <p>{error}</p>
        <Button
          variant="outline"
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
    <p className="p-4">Loading file…</p>
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
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  const known = useRef<Set<string> | null>(null);
  const open = useCallback((item: Artifact) => {
    setSelected(item);
  }, []);
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
  return (
    <ArtifactContext.Provider value={{ items, open }}>
      <div className="relative flex h-full min-w-0">
        <div className="flex min-w-0 flex-1 flex-col">
          {(items.length > 0 || error) && (
            <div
              className="flex shrink-0 gap-2 overflow-x-auto border-b p-2"
              aria-label="Conversation files"
            >
              {error ? (
                <Button
                  variant="ghost"
                  onClick={() => {
                    setAttempt((x) => x + 1);
                  }}
                >
                  Retry loading files
                </Button>
              ) : (
                items.map((item) => (
                  <Button
                    key={item.id}
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      open(item);
                    }}
                  >
                    <FileText className="size-4" />
                    {item.title}
                  </Button>
                ))
              )}
            </div>
          )}
          <div className="min-h-0 flex-1">{children}</div>
        </div>
        {selected && (
          <aside
            aria-label="Artifact viewer"
            className="absolute inset-0 z-30 flex min-w-0 flex-col border-l bg-background md:static md:w-1/2 md:min-w-80"
          >
            <header className="flex items-center gap-2 border-b p-3">
              <h2 className="min-w-0 flex-1 truncate font-medium">
                {selected.title}
              </h2>
              <a
                href={contentUrl(selected)}
                download={selected.filename}
                className="text-sm underline"
              >
                Download
              </a>
              <Button
                size="icon"
                variant="ghost"
                aria-label="Close artifact viewer"
                onClick={() => {
                  setSelected(undefined);
                }}
              >
                <X className="size-4" />
              </Button>
            </header>
            {selected.temporary && (
              <p className="border-b bg-muted p-3 text-sm">
                Temporary file — available while its execution environment is
                retained. Download it to keep a copy.
              </p>
            )}
            <div className="min-h-0 flex-1 overflow-auto">
              <Preview key={selected.id} artifact={selected} />
            </div>
          </aside>
        )}
      </div>
    </ArtifactContext.Provider>
  );
}

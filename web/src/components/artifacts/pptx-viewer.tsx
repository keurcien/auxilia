/* eslint-disable @next/next/no-img-element -- Generated blob images do not use Next image optimization. */
"use client";

import { useEffect, useRef, useState } from "react";
import { getSlides, loadPresentation } from "@office-kit/pptx";
import { renderSlideToSvg } from "@office-kit/pptx-preview";
import DOMPurify from "dompurify";
import { ChevronLeft, ChevronRight, Loader2, Maximize } from "lucide-react";
import { cn } from "@/lib/utils";
import { Loading } from "./viewers";
import type { ViewerProps } from "./viewers";

export default function PptxViewer({ bytes }: ViewerProps) {
  const [slides, setSlides] = useState<string[]>([]);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<string>();
  // Slides render one by one and show as they land; `total` is the deck size.
  const [total, setTotal] = useState(0);
  useEffect(() => {
    let active = true;
    const urls: string[] = [];
    const revokeAll = () => {
      urls.forEach((url) => {
        URL.revokeObjectURL(url);
      });
      urls.length = 0;
    };
    type Presentation = Awaited<ReturnType<typeof loadPresentation>>;
    type Slide = ReturnType<typeof getSlides>[number];
    // One slide per task, so the panel stays responsive and each slide shows
    // as soon as it is ready.
    const renderNext = (
      presentation: Presentation,
      deck: readonly Slide[],
      index: number,
    ): Promise<void> => {
      const slide = deck.at(index);
      if (!active || !slide) return Promise.resolve();
      // SVG is untrusted document content. Sanitize, then use image context
      // (never insert the renderer's SVG directly into the host DOM).
      const svg = DOMPurify.sanitize(
        renderSlideToSvg(presentation, slide, { textLayout: "svg" }),
        {
          USE_PROFILES: { svg: true, svgFilters: true },
          FORBID_TAGS: ["foreignObject", "a"],
        },
      );
      urls.push(
        URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" })),
      );
      setSlides([...urls]);
      return new Promise((resolve) => setTimeout(resolve, 0)).then(() =>
        renderNext(presentation, deck, index + 1),
      );
    };
    loadPresentation(new Uint8Array(bytes))
      .then((presentation) => {
        const deck = getSlides(presentation);
        if (!deck.length) throw new Error("This presentation has no slides.");
        if (deck.length > 200)
          throw new Error(
            "This deck exceeds the 200-slide preview limit. Download it to view all slides.",
          );
        setTotal(deck.length);
        return renderNext(presentation, deck, 0);
      })
      .catch((cause: unknown) => {
        // The error view replaces the slides: free what was rendered so far.
        revokeAll();
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not preview this presentation.",
          );
      });
    return () => {
      active = false;
      revokeAll();
    };
  }, [bytes]);
  const count = slides.length;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!count) return;
      // Leave arrow keys to text fields and to the panel's resize handle.
      if (
        event.target instanceof Element &&
        event.target.closest(
          'input, textarea, select, [contenteditable], [role="separator"]',
        )
      )
        return;
      if (event.key === "ArrowLeft") setSelected((x) => Math.max(0, x - 1));
      if (event.key === "ArrowRight")
        setSelected((x) => Math.min(count - 1, x + 1));
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [count]);
  const stage = useRef<HTMLDivElement>(null);
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    strip.current?.children.item(selected)?.scrollIntoView({
      block: "nearest",
      inline: "nearest",
    });
  }, [selected]);
  if (error)
    return (
      <p
        role="alert"
        className="flex h-full items-center justify-center bg-neutral-bg p-6 text-center text-sm text-subtle"
      >
        {error}
      </p>
    );
  if (!count)
    return (
      <Loading
        className="bg-neutral-bg"
        label={
          total ? `Rendering slide 1 of ${total}…` : "Opening presentation…"
        }
      />
    );
  const navButton =
    "flex size-7 items-center justify-center rounded-full text-ink hover:bg-hover disabled:text-ghost disabled:hover:bg-transparent";
  return (
    <div className="flex h-full flex-col">
      <div
        ref={stage}
        className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3.5 bg-neutral-bg p-6"
      >
        <div className="flex min-h-0 w-full flex-1 items-center justify-center">
          <img
            alt={`Slide ${selected + 1}`}
            src={slides.at(selected)}
            className="max-h-full max-w-full rounded bg-white object-contain shadow-[0_1px_2px_rgba(10,25,30,0.08),0_10px_30px_rgba(10,25,30,0.12)]"
          />
        </div>
        <div className="flex flex-none items-center gap-1 rounded-full border border-border bg-white p-[3px] shadow-[0_2px_8px_rgba(10,25,30,0.06)]">
          <button
            type="button"
            aria-label="Previous slide"
            disabled={selected === 0}
            className={navButton}
            onClick={() => {
              setSelected((x) => x - 1);
            }}
          >
            <ChevronLeft className="size-3.5" />
          </button>
          <span className="min-w-10 px-1.5 text-center font-mono text-[11.5px] text-ink">
            {selected + 1} / {total || count}
          </span>
          <button
            type="button"
            aria-label="Next slide"
            disabled={selected === count - 1}
            className={navButton}
            onClick={() => {
              setSelected((x) => x + 1);
            }}
          >
            <ChevronRight className="size-3.5" />
          </button>
          <span className="mx-0.5 h-4 w-px bg-hairline" />
          <button
            type="button"
            aria-label="Full screen"
            title="Full screen"
            className={cn(navButton, "text-subtle")}
            onClick={() => {
              // Denied by the browser or an embedding policy: stay inline.
              stage.current?.requestFullscreen().catch(() => undefined);
            }}
          >
            <Maximize className="size-3" />
          </button>
        </div>
      </div>
      {total > 1 && (
        <div
          ref={strip}
          className="flex flex-none gap-2.5 overflow-x-auto border-t border-hairline px-5 py-3"
        >
          {slides.map((url, index) => (
            <button
              key={url}
              type="button"
              aria-label={`Go to slide ${index + 1}`}
              aria-current={index === selected}
              onClick={() => {
                setSelected(index);
              }}
              className="flex flex-none flex-col items-center gap-1"
            >
              <img
                alt=""
                src={url}
                className={cn(
                  "h-[58px] w-[104px] rounded bg-white object-contain",
                  index === selected
                    ? "outline-2 outline-offset-2 outline-petrol"
                    : "border border-border",
                )}
              />
              <span
                className={cn(
                  "font-mono text-[10px]",
                  index === selected
                    ? "font-semibold text-petrol"
                    : "text-meta",
                )}
              >
                {index + 1}
              </span>
            </button>
          ))}
          {count < total && (
            <div
              role="status"
              aria-label={`Rendering slide ${count + 1} of ${total}`}
              className="flex h-[58px] w-[104px] flex-none items-center justify-center rounded border border-dashed border-border text-meta"
            >
              <Loader2 className="size-4 animate-spin text-petrol" />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

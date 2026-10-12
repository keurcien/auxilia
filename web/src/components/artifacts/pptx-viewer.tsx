/* eslint-disable @next/next/no-img-element -- Generated blob images do not use Next image optimization. */
"use client";

import { useEffect, useState } from "react";
import { getSlides, loadPresentation } from "@office-kit/pptx";
import { renderSlideToSvg } from "@office-kit/pptx-preview";
import DOMPurify from "dompurify";
import type { ViewerProps } from "./viewers";

export default function PptxViewer({ bytes }: ViewerProps) {
  const [slides, setSlides] = useState<string[]>([]);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    const urls: string[] = [];
    async function load() {
      try {
        const presentation = await loadPresentation(new Uint8Array(bytes));
        const deck = getSlides(presentation);
        if (!deck.length) throw new Error("This presentation has no slides.");
        if (deck.length > 200)
          throw new Error(
            "This deck exceeds the 200-slide preview limit. Download it to view all slides.",
          );
        for (const slide of deck) {
          if (!active) return;
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
          await new Promise((resolve) => setTimeout(resolve, 0));
        }
        if (active) setSlides([...urls]);
      } catch (cause) {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not preview this presentation.",
          );
      }
    }
    void load();
    return () => {
      active = false;
      urls.forEach((url) => {
        URL.revokeObjectURL(url);
      });
    };
  }, [bytes]);
  if (error)
    return (
      <p role="alert" className="p-4 text-sm">
        {error}
      </p>
    );
  if (!slides.length) return <p className="p-4">Rendering slides…</p>;
  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <p className="text-xs text-muted-foreground">
        Preview may differ from PowerPoint. Download the original for full
        fidelity.
      </p>
      <div className="flex items-center justify-between">
        <button
          disabled={selected === 0}
          onClick={() => {
            setSelected((x) => x - 1);
          }}
        >
          Previous
        </button>
        <span>
          Slide {selected + 1} of {slides.length}
        </span>
        <button
          disabled={selected === slides.length - 1}
          onClick={() => {
            setSelected((x) => x + 1);
          }}
        >
          Next
        </button>
      </div>
      <img
        alt={`Slide ${selected + 1}`}
        src={slides[selected]}
        className="min-h-0 w-full flex-1 object-contain"
      />
    </div>
  );
}

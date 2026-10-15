/* eslint-disable @next/next/no-img-element -- Generated blob images do not use Next image optimization. */
"use client";

import { useEffect, useRef, useState } from "react";
import {
  getGroupChildren,
  getParagraphAlignment,
  getShapeBoundsResolved,
  getShapeId,
  getShapeKind,
  getShapeRunFormatEffective,
  getShapeText,
  getShapeTextMargins,
  getSlides,
  getSlideShapes,
  getSlideSize,
  hasShapeText,
  loadPresentation,
  savePresentation,
  setShapeText,
} from "@office-kit/pptx";
import { renderSlideToSvg } from "@office-kit/pptx-preview";
import DOMPurify from "dompurify";
import type { CSSProperties } from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Maximize,
  Pencil,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Loading } from "./viewers";
import type { ViewerProps } from "./viewers";

type Presentation = Awaited<ReturnType<typeof loadPresentation>>;
type Slide = ReturnType<typeof getSlides>[number];
type Shape = ReturnType<typeof getSlideShapes>[number];

/** The rendered slide minus one shape's paragraphs (the renderer tags them). */
export function withoutText(svg: string, shapeId: number): string {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  doc
    .querySelectorAll(`[data-pptx-shape-id="${shapeId}"] [data-pptx-paragraph]`)
    .forEach((paragraph) => {
      paragraph.remove();
    });
  return new XMLSerializer().serializeToString(doc);
}

/** `hideTextOf`: a shape id whose text is left out, so an in-place editor
 *  over it shows the slide (fill, borders) without the text twice. */
function slideUrl(
  presentation: Presentation,
  slide: Slide,
  hideTextOf?: number,
): string {
  // SVG is untrusted document content. Sanitize, then use image context
  // (never insert the renderer's SVG directly into the host DOM).
  let svg = DOMPurify.sanitize(
    renderSlideToSvg(presentation, slide, { textLayout: "svg" }),
    {
      USE_PROFILES: { svg: true, svgFilters: true },
      FORBID_TAGS: ["foreignObject", "a"],
    },
  );
  if (hideTextOf !== undefined) svg = withoutText(svg, hideTextOf);
  return URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
}

const ALIGN: Record<string, CSSProperties["textAlign"]> = {
  l: "left",
  ctr: "center",
  r: "right",
  just: "justify",
  dist: "justify",
};

/** The shape's first-run typography as CSS, in `cqw` of the slide box so it
 *  scales with the rendered slide. */
export function textStyle(
  presentation: Presentation,
  shape: Shape,
  slideWidth: number,
): CSSProperties {
  // EMU (12700 per point) → percent of the slide width, as container units.
  const cqw = (emu: number) => `${(emu / slideWidth) * 100}cqw`;
  const run = getShapeRunFormatEffective(presentation, shape, 0, 0);
  const margins = getShapeTextMargins(shape);
  // PowerPoint's default insets: 0.1in left/right, 0.05in top/bottom.
  const inset = (value: number | null | undefined, fallback: number) =>
    cqw(value ?? fallback);
  return {
    fontFamily: run.font ? `"${run.font}", sans-serif` : undefined,
    fontSize: cqw((run.size ?? 18) * 12700),
    fontWeight: run.bold ? 700 : 400,
    fontStyle: run.italic ? "italic" : undefined,
    color: run.color ?? undefined,
    letterSpacing: run.spc ? cqw((run.spc / 100) * 12700) : undefined,
    lineHeight: 1.2,
    textAlign: ALIGN[getParagraphAlignment(shape, 0) ?? "l"],
    padding: [
      inset(margins?.top, 45720),
      inset(margins?.right, 91440),
      inset(margins?.bottom, 45720),
      inset(margins?.left, 91440),
    ].join(" "),
  };
}

/** Text shapes a click can edit, with bounds as fractions of the slide. */
export function textBoxes(presentation: Presentation, slide: Slide) {
  const size = getSlideSize(presentation);
  if (!size) return [];
  const shapes = getSlideShapes(slide);
  // shortcut: group children sit in their group's coordinate space, so they
  // are skipped; map them through getGroupTransform if decks need them.
  const grouped = new Set(
    shapes
      .filter((shape) => getShapeKind(shape) === "group")
      .flatMap((group) => getGroupChildren(group)),
  );
  return shapes.flatMap((shape) => {
    const bounds = getShapeBoundsResolved(presentation, shape);
    if (grouped.has(shape) || !bounds || !hasShapeText(shape)) return [];
    return [
      {
        shape,
        left: bounds.x / size.width,
        top: bounds.y / size.height,
        width: bounds.w / size.width,
        height: bounds.h / size.height,
        text: textStyle(presentation, shape, size.width),
      },
    ];
  });
}

export default function PptxViewer({ bytes, onSave }: ViewerProps) {
  const [slides, setSlides] = useState<string[]>([]);
  const [selected, setSelected] = useState(0);
  const [error, setError] = useState<string>();
  // Slides render one by one and show as they land; `total` is the deck size.
  const [total, setTotal] = useState(0);
  // The loaded deck stays mutable: edits apply to it, then it is saved whole.
  const [loaded, setLoaded] = useState<{
    presentation: Presentation;
    deck: readonly Slide[];
  }>();
  const urlsRef = useRef<string[]>([]);
  const [ratio, setRatio] = useState(16 / 9);
  const [editing, setEditing] = useState(false);
  // `url`: the slide rendered without this shape's text, shown while editing.
  const [target, setTarget] = useState<{
    shape: Shape;
    text: string;
    url: string;
  }>();
  const endEdit = () => {
    if (target) URL.revokeObjectURL(target.url);
    setTarget(undefined);
  };
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string>();
  useEffect(() => {
    let active = true;
    const urls: string[] = [];
    urlsRef.current = urls;
    const revokeAll = () => {
      urls.forEach((url) => {
        URL.revokeObjectURL(url);
      });
      urls.length = 0;
    };
    // One slide per task, so the panel stays responsive and each slide shows
    // as soon as it is ready.
    const renderNext = (
      presentation: Presentation,
      deck: readonly Slide[],
      index: number,
    ): Promise<void> => {
      const slide = deck.at(index);
      if (!active || !slide) return Promise.resolve();
      urls.push(slideUrl(presentation, slide));
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
        setLoaded({ presentation, deck });
        const size = getSlideSize(presentation);
        if (size) setRatio(size.width / size.height);
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
  const applyEdit = () => {
    const slide = loaded?.deck.at(selected);
    if (!loaded || !slide || !target) return;
    endEdit();
    if (target.text === getShapeText(target.shape)) return;
    setShapeText(target.shape, target.text, { preserveFormatting: true });
    const urls = urlsRef.current;
    const previous = urls[selected];
    urls[selected] = slideUrl(loaded.presentation, slide);
    URL.revokeObjectURL(previous);
    setSlides([...urls]);
    setDirty(true);
  };
  const save = async () => {
    if (!loaded || !onSave) return;
    setSaving(true);
    setSaveError(undefined);
    try {
      // On success the panel reloads the saved file into a fresh viewer.
      await onSave(await savePresentation(loaded.presentation));
    } catch (cause) {
      setSaveError(
        cause instanceof Error ? cause.message : "Could not save your changes.",
      );
      setSaving(false);
    }
  };
  const slide = loaded?.deck.at(selected);
  const boxes =
    editing && loaded && slide ? textBoxes(loaded.presentation, slide) : [];
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
        {/* Size containment: the slide box fits both axes at the deck's ratio,
            so edit targets line up with the rendered slide. */}
        <div
          className="flex min-h-0 w-full flex-1 items-center justify-center"
          style={{ containerType: "size" }}
        >
          <div
            className="relative"
            style={{
              aspectRatio: ratio,
              width: `min(100cqw, calc(100cqh * ${ratio}))`,
              // Text sizes inside are in cqw of this box.
              containerType: "inline-size",
            }}
          >
            <img
              alt={`Slide ${selected + 1}`}
              src={target?.url ?? slides.at(selected)}
              className="h-full w-full rounded bg-white object-contain shadow-[0_1px_2px_rgba(10,25,30,0.08),0_10px_30px_rgba(10,25,30,0.12)]"
            />
            {boxes.map((box, index) => {
              const style = {
                left: `${box.left * 100}%`,
                top: `${box.top * 100}%`,
                width: `${box.width * 100}%`,
                minHeight: `${box.height * 100}%`,
              };
              // The shape being edited becomes its own textarea, in place.
              return target?.shape === box.shape ? (
                <textarea
                  key={index}
                  autoFocus
                  aria-label="Text"
                  value={target.text}
                  style={{ ...style, ...box.text }}
                  onChange={(event) => {
                    setTarget({ ...target, text: event.target.value });
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      // Blur fires on unmount too: mark it so it does not apply.
                      event.currentTarget.dataset.cancelled = "true";
                      endEdit();
                    }
                    if (
                      event.key === "Enter" &&
                      (event.metaKey || event.ctrlKey)
                    ) {
                      event.preventDefault();
                      applyEdit();
                    }
                  }}
                  // Clicking away applies, like editing a text box in PowerPoint.
                  onBlur={(event) => {
                    if (!event.currentTarget.dataset.cancelled) applyEdit();
                  }}
                  className="absolute z-10 resize-none overflow-hidden rounded-sm bg-transparent outline-2 outline-petrol [field-sizing:content]"
                />
              ) : (
                <button
                  key={index}
                  type="button"
                  aria-label={`Edit text: ${getShapeText(box.shape).slice(0, 60)}`}
                  onClick={() => {
                    if (!loaded || !slide) return;
                    setTarget({
                      shape: box.shape,
                      text: getShapeText(box.shape),
                      url: slideUrl(
                        loaded.presentation,
                        slide,
                        getShapeId(box.shape),
                      ),
                    });
                  }}
                  style={{ ...style, height: style.minHeight }}
                  className="absolute cursor-text rounded-sm outline-1 outline-dashed outline-petrol/50 hover:bg-petrol/10 focus-visible:outline-2 focus-visible:outline-solid focus-visible:outline-petrol"
                />
              );
            })}
          </div>
        </div>
        {saveError && (
          <p role="alert" className="flex-none text-[12px] text-destructive">
            {saveError}
          </p>
        )}
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
          {onSave && (
            <button
              type="button"
              aria-label="Edit text"
              title="Edit text"
              aria-pressed={editing}
              className={cn(
                navButton,
                editing ? "bg-petrol-tint text-petrol" : "text-subtle",
              )}
              onClick={() => {
                setEditing((x) => !x);
                endEdit();
              }}
            >
              <Pencil className="size-3" />
            </button>
          )}
          {onSave && dirty && (
            <button
              type="button"
              disabled={saving}
              onClick={() => {
                void save();
              }}
              className="flex h-7 items-center gap-1 rounded-full bg-petrol px-2.5 text-[11.5px] font-semibold text-white hover:bg-petrol/90 disabled:opacity-60"
            >
              {saving ? (
                <Loader2 className="size-3 animate-spin" />
              ) : (
                <Check className="size-3" />
              )}
              Save
            </button>
          )}
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

/* eslint-disable @next/next/no-img-element -- Generated blob images do not use Next image optimization. */
"use client";

import { useEffect, useRef, useState } from "react";
import {
  getGroupChildren,
  getParagraphPropertiesEffective,
  getShapeBodyPrEffective,
  getShapeBoundsResolved,
  getShapeId,
  getShapeKind,
  getShapeRunFormatEffective,
  getShapeText,
  getPresentationFonts,
  getSlides,
  getSlideShapes,
  getSlideSize,
  hasShapeText,
  isShapePlaceholder,
  isShapeTextBox,
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
import {
  fontRendering,
  lineMetrics,
  loadFonts,
  resolvedFamily,
} from "./deck-fonts";
import type { DeckFonts } from "./deck-fonts";
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

/** The slide with `css` (our own `@font-face` rules) as its first child: an
 *  SVG shown as an image cannot fetch fonts, so they travel inline. */
export function withFonts(svg: string, css: string): string {
  if (!css) return svg;
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  const style = doc.createElementNS("http://www.w3.org/2000/svg", "style");
  style.textContent = css;
  doc.documentElement.prepend(style);
  return new XMLSerializer().serializeToString(doc);
}

/** `hideTextOf`: a shape id whose text is left out, so an in-place editor
 *  over it shows the slide (fill, borders) without the text twice.
 *  `families`: the authored font names the slide uses. */
function renderSlide(
  presentation: Presentation,
  slide: Slide,
  fonts: DeckFonts,
  hideTextOf?: number,
): { url: string; families: ReadonlySet<string> } {
  const rendering = fontRendering(fonts);
  // SVG is untrusted document content. Sanitize, then use image context
  // (never insert the renderer's SVG directly into the host DOM).
  let svg = DOMPurify.sanitize(
    renderSlideToSvg(presentation, slide, rendering.options),
    {
      USE_PROFILES: { svg: true, svgFilters: true },
      FORBID_TAGS: ["foreignObject", "a"],
    },
  );
  if (hideTextOf !== undefined) svg = withoutText(svg, hideTextOf);
  svg = withFonts(svg, rendering.css());
  return {
    url: URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" })),
    families: rendering.seen,
  };
}

// Waiting longer than this for theme fonts shows the substitute first.
const THEME_FONT_WAIT_MS = 1500;

const ALIGN: Record<string, CSSProperties["textAlign"]> = {
  l: "left",
  left: "left",
  ctr: "center",
  center: "center",
  r: "right",
  right: "right",
  just: "justify",
  justify: "justify",
  dist: "justify",
  distribute: "justify",
};

const ANCHOR_SHARE = { top: 0, center: 0.5, bottom: 1 };

// The renderer drops the first baseline by this share of ascent + descent.
const BASELINE_LEADING_DROP = 0.036;

/** The shape's first-run typography as CSS, in `cqw` of the slide box so it
 *  scales with the rendered slide. Mirrors the renderer's text layout (font,
 *  autofit scale, line advance, insets, alignment, anchor) so swapping the
 *  rendered text for the editor moves nothing. */
export function textStyle(
  presentation: Presentation,
  shape: Shape,
  slideWidth: number,
  fonts: DeckFonts,
): { style: CSSProperties; anchor: "top" | "center" | "bottom" } {
  // EMU (12700 per point) → percent of the slide width, as container units.
  const cqw = (emu: number) => `${(emu / slideWidth) * 100}cqw`;
  const run = getShapeRunFormatEffective(presentation, shape, 0, 0);
  const paragraph = getParagraphPropertiesEffective(presentation, shape, 0);
  const body = getShapeBodyPrEffective(presentation, shape);
  const fontScale = body.autoFitParams?.fontScale ?? 1;
  const lineScale = 1 - (body.autoFitParams?.lnSpcReduction ?? 0);
  const size = (run.size ?? 18) * 12700 * fontScale;
  const font = lineMetrics(fonts, run.font ?? null, !!run.bold, !!run.italic);
  const spacing = paragraph.lineSpacing;
  const advance =
    spacing?.kind === "pts"
      ? spacing.value * 12700 * fontScale
      : size *
        (font.ascent + font.descent + font.lineGap) *
        (spacing?.kind === "pct" ? spacing.value : 1);
  // Shapes other than text boxes and placeholders center their text.
  const autoshape = !isShapePlaceholder(shape) && !isShapeTextBox(shape);
  // PowerPoint's default insets: 0.1in left/right, 0.05in top/bottom.
  const { margins } = body;
  return {
    anchor: body.anchor ?? (autoshape ? "center" : "top"),
    style: {
      // No generic fallback: the slide image has none either.
      fontFamily: `"${resolvedFamily(fonts, run.font ?? null)}"`,
      fontSize: cqw(size),
      fontWeight: run.bold ? 700 : 400,
      fontStyle: run.italic ? "italic" : undefined,
      color: run.color ?? undefined,
      letterSpacing: run.spc ? cqw((run.spc / 100) * 12700) : undefined,
      lineHeight: cqw(advance * lineScale),
      textAlign: ALIGN[paragraph.align ?? (autoshape ? "ctr" : "l")],
      padding: [
        cqw(margins.top ?? 45720),
        cqw(margins.right ?? 91440),
        cqw(margins.bottom ?? 45720),
        cqw(margins.left ?? 91440),
      ].join(" "),
      marginTop: cqw(BASELINE_LEADING_DROP * (font.ascent + font.descent) * size),
    },
  };
}

/** Text shapes a click can edit, with bounds as fractions of the slide. */
export function textBoxes(
  presentation: Presentation,
  slide: Slide,
  fonts: DeckFonts = new Map(),
) {
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
        ...textStyle(presentation, shape, size.width, fonts),
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
  // The ref serves the render loop; the state re-renders the editor boxes.
  const fontsRef = useRef<DeckFonts>(new Map());
  const [fonts, setFonts] = useState<DeckFonts>(() => new Map());
  const [ratio, setRatio] = useState(16 / 9);
  const [editing, setEditing] = useState(false);
  // `url`: the slide rendered without this shape's text, shown while editing.
  const [target, setTarget] = useState<{
    shape: Shape;
    text: string;
    url: string;
  }>();
  // The effect below revokes the edit's slide image.
  const endEdit = () => {
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
    // Per slide: the font names it uses, and the fonts loaded when drawn.
    const drawn = new Map<
      number,
      { families: ReadonlySet<string>; fonts: DeckFonts }
    >();
    const draw = (presentation: Presentation, slide: Slide, index: number) => {
      const fonts = fontsRef.current;
      const rendered = renderSlide(presentation, slide, fonts);
      const previous = urls.at(index);
      if (previous) URL.revokeObjectURL(previous);
      urls.splice(index, 1, rendered.url);
      drawn.set(index, { families: rendered.families, fonts });
      setSlides([...urls]);
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
      draw(presentation, slide, index);
      return new Promise((resolve) => setTimeout(resolve, 0)).then(() =>
        renderNext(presentation, deck, index + 1),
      );
    };
    const addFonts = (loaded: DeckFonts) => {
      fontsRef.current = new Map([...fontsRef.current, ...loaded]);
      setFonts(fontsRef.current);
    };
    /** Load the fonts the slides turned out to use, then redraw each slide
     *  drawn before one of its fonts was available. */
    const loadUsedFonts = async (
      presentation: Presentation,
      deck: readonly Slide[],
    ) => {
      addFonts(
        await loadFonts(
          [...drawn.values()].flatMap(({ families }) => [...families]),
        ),
      );
      for (const [index, slide] of deck.entries()) {
        if (!active) return;
        const slideFonts = drawn.get(index);
        const stale = [...(slideFonts?.families ?? [])].some(
          (name) => fontsRef.current.has(name) && !slideFonts?.fonts.has(name),
        );
        if (!stale) continue;
        draw(presentation, slide, index);
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
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
        const theme = getPresentationFonts(presentation);
        const themeFonts = [theme?.majorLatin, theme?.minorLatin].filter(
          (name): name is string => !!name,
        );
        return Promise.race([
          loadFonts(themeFonts).then(addFonts),
          new Promise((resolve) => setTimeout(resolve, THEME_FONT_WAIT_MS)),
        ])
          .then(() => renderNext(presentation, deck, 0))
          .then(() => loadUsedFonts(presentation, deck));
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
    const [previous] = urls.splice(
      selected,
      1,
      renderSlide(loaded.presentation, slide, fontsRef.current).url,
    );
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
  // Saving became unavailable (a turn started): leave edit mode with it.
  if (editing && !onSave) {
    setEditing(false);
    endEdit();
  }
  // No edits while saving: the saved file reloads into a fresh viewer.
  const boxes =
    editing && !saving && loaded && slide
      ? textBoxes(loaded.presentation, slide, fonts)
      : [];
  // An edit open at unmount still holds its slide image.
  const targetUrl = target?.url;
  useEffect(
    () => () => {
      if (targetUrl) URL.revokeObjectURL(targetUrl);
    },
    [targetUrl],
  );
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
                  // A centered or bottom-anchored body grows from that edge.
                  style={{
                    ...style,
                    ...box.style,
                    minHeight: box.anchor === "top" ? style.minHeight : undefined,
                    top: `${(box.top + box.height * ANCHOR_SHARE[box.anchor]) * 100}%`,
                    translate: `0 ${-ANCHOR_SHARE[box.anchor] * 100}%`,
                  }}
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
                      url: renderSlide(
                        loaded.presentation,
                        slide,
                        fontsRef.current,
                        getShapeId(box.shape),
                      ).url,
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

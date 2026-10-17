import {
  defaultMeasurer,
  substituteFamily,
  type FontSpec,
  type MeasureResult,
  type RenderSlideOptions,
} from "@office-kit/pptx-preview";

/** One loaded style of a font: what to match a run against, and the
 *  `@font-face` rule (font inlined as a data URI) a slide SVG embeds. */
export interface Face {
  readonly bold: boolean;
  readonly italic: boolean;
  readonly rule: string;
}

/** Loaded families of one deck, keyed by the authored name. */
export type DeckFonts = ReadonlyMap<string, readonly Face[]>;

// Deck font names are untrusted and end up in CSS and a URL; Google Fonts
// names are letters, digits and spaces only.
const SAFE_NAME = /^[A-Za-z0-9 ]{1,64}$/;

const families = new Map<string, Promise<Face[]>>();

/** Faces of `family` from Google Fonts, Latin subset only; `[]` when Google
 *  has no such family or the network fails. Registered on the page too, so
 *  HTML over the slide (the text editor) uses the same font. */
export function loadFamily(family: string): Promise<Face[]> {
  if (!SAFE_NAME.test(family)) return Promise.resolve([]);
  let faces = families.get(family);
  if (!faces) {
    // A family Google lacks stays cached as `[]`; a failed fetch is retried.
    faces = fetchFamily(family).catch(() => {
      families.delete(family);
      return [];
    });
    families.set(family, faces);
  }
  return faces;
}

export async function loadFonts(names: Iterable<string>): Promise<DeckFonts> {
  const loaded = await Promise.all(
    [...new Set(names)].map(
      async (name) => [name, await loadFamily(name)] as const,
    ),
  );
  return new Map(loaded.filter(([, faces]) => faces.length));
}

async function fetchFamily(family: string): Promise<Face[]> {
  // Google serves the styles a family has and answers 400 for an unknown one.
  const response = await fetch(
    `https://fonts.googleapis.com/css2?family=${family.replaceAll(" ", "+")}:ital,wght@0,400;0,700;1,400;1,700`,
  );
  return response.ok ? parseFaces(family, await response.text()) : [];
}

/** The Latin `@font-face` blocks of a Google Fonts stylesheet, fetched,
 *  inlined and registered with `document.fonts`. */
async function parseFaces(family: string, css: string): Promise<Face[]> {
  const blocks = [...css.matchAll(/\/\* latin \*\/\s*@font-face\s*{([^}]*)}/g)];
  return Promise.all(
    blocks.flatMap(([, block]) => {
      const url = /url\((https:\/\/fonts\.gstatic\.com\/[^)]+)\)/.exec(block)?.[1];
      if (!url) return [];
      const italic = /font-style:\s*italic/.test(block);
      const weight = /font-weight:\s*(\d+)/.exec(block)?.[1] ?? "400";
      return [
        fetch(url)
          .then((response) => response.arrayBuffer())
          .then(async (bytes) => {
            const style = italic ? "italic" : "normal";
            const face = new FontFace(family, bytes, { style, weight });
            document.fonts.add(await face.load());
            return {
              bold: Number(weight) >= 600,
              italic,
              rule: `@font-face{font-family:"${family}";font-style:${style};font-weight:${weight};src:url(${await dataUrl(bytes)}) format("woff2")}`,
            };
          }),
      ];
    }),
  );
}

function dataUrl(bytes: ArrayBuffer): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      resolve(reader.result as string);
    };
    reader.onerror = () => {
      reject(reader.error ?? new Error("Could not read font"));
    };
    reader.readAsDataURL(new Blob([bytes], { type: "font/woff2" }));
  });
}

/** Face for a run: exact style, else same weight, else any. */
export function pickFace(
  faces: readonly Face[],
  bold: boolean,
  italic: boolean,
): Face | undefined {
  return (
    faces.find((face) => face.bold === bold && face.italic === italic) ??
    faces.find((face) => face.bold === bold) ??
    faces.at(0)
  );
}

let context: CanvasRenderingContext2D | null | undefined;

/** A run measured with a loaded font, on a canvas: the same measurement as
 *  the renderer's own browser measurer. `undefined` without a canvas. */
function measureLoaded(text: string, spec: FontSpec): MeasureResult | undefined {
  context ??=
    typeof document === "undefined"
      ? null
      : document.createElement("canvas").getContext("2d");
  if (!context) return undefined;
  context.font = `${spec.italic ? "italic" : "normal"} ${spec.bold ? "bold" : "normal"} ${spec.sizePx}px "${spec.family}"`;
  context.fontKerning = spec.kerning === false ? "none" : "normal";
  context.letterSpacing = `${spec.letterSpacingPx}px`;
  const metrics = context.measureText(text);
  return {
    widthPx: metrics.width,
    ascentPx: metrics.fontBoundingBoxAscent,
    descentPx: metrics.fontBoundingBoxDescent,
    lineGapPx: 0,
    inkAscentPx: metrics.actualBoundingBoxAscent,
    inkDescentPx: metrics.actualBoundingBoxDescent,
  };
}

/** The family the renderer draws an authored name with. */
export function resolvedFamily(fonts: DeckFonts, family: string | null) {
  return family && fonts.has(family) ? family : substituteFamily(family);
}

/** Vertical metrics in em the renderer lays a run's lines out with: the
 *  font's own when loaded, else its fallback ratios (0.9 / 0.22 / 0.08). */
export function lineMetrics(
  fonts: DeckFonts,
  family: string | null,
  bold: boolean,
  italic: boolean,
) {
  const measured =
    family && fonts.has(family)
      ? measureLoaded("Mg", {
          family,
          sizePx: 100,
          bold,
          italic,
          letterSpacingPx: 0,
        })
      : undefined;
  return measured
    ? {
        ascent: (measured.ascentPx ?? 0) / 100,
        descent: (measured.descentPx ?? 0) / 100,
        lineGap: 0,
      }
    : { ascent: 0.9, descent: 0.22, lineGap: 0.08 };
}

/** Render options that keep loaded families (others fall back to the
 *  renderer's substitutes), plus what the render touched: the authored
 *  families it saw and the `@font-face` rules the SVG must embed. */
export function fontRendering(fonts: DeckFonts) {
  const seen = new Set<string>();
  const used = new Set<Face>();
  const measure = (text: string, spec: FontSpec): MeasureResult => {
    const faces = fonts.get(spec.family);
    const face = faces && pickFace(faces, spec.bold, spec.italic);
    if (!face) return defaultMeasurer(text, spec);
    used.add(face);
    return measureLoaded(text, spec) ?? defaultMeasurer(text, spec);
  };
  const options: RenderSlideOptions = {
    textLayout: "svg",
    resolveFamily: (family) => {
      if (family) seen.add(family);
      return resolvedFamily(fonts, family);
    },
    measureText: measure,
  };
  return {
    options,
    seen,
    css: () => [...used].map((face) => face.rule).join(""),
  };
}

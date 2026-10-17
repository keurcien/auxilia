import { afterEach, describe, expect, it, vi } from "vitest";
import {
  addBlankSlide,
  addSlideTextBox,
  createPresentation,
  inches,
  setShapeTextFormat,
} from "@office-kit/pptx";
import { renderSlideToSvg } from "@office-kit/pptx-preview";
import { fontRendering, loadFamily, pickFace } from "./deck-fonts";
import { withFonts } from "./pptx-viewer";

const STYLESHEET = `
/* cyrillic */
@font-face {
  font-family: 'Lora';
  font-style: normal;
  font-weight: 400;
  src: url(https://fonts.gstatic.com/s/lora/cyrillic.woff2) format('woff2');
}
/* latin */
@font-face {
  font-family: 'Lora';
  font-style: normal;
  font-weight: 400;
  src: url(https://fonts.gstatic.com/s/lora/latin-400.woff2) format('woff2');
}
/* latin */
@font-face {
  font-family: 'Lora';
  font-style: normal;
  font-weight: 700;
  src: url(https://fonts.gstatic.com/s/lora/latin-700.woff2) format('woff2');
}
`;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("loadFamily", () => {
  it("inlines and registers the Latin faces", async () => {
    const requests: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        requests.push(url);
        if (url.startsWith("https://fonts.googleapis.com"))
          return Promise.resolve(new Response(STYLESHEET));
        return Promise.resolve(new Response(new Uint8Array([1, 2, 3])));
      }),
    );
    const added: unknown[] = [];
    vi.stubGlobal(
      "FontFace",
      class {
        constructor(
          readonly family: string,
          readonly source: ArrayBuffer,
          readonly descriptors: FontFaceDescriptors,
        ) {}
        load() {
          return Promise.resolve(this);
        }
      },
    );
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { add: (face: unknown) => added.push(face) },
    });

    const faces = await loadFamily("Lora");

    expect(requests[0]).toBe(
      "https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,700;1,400;1,700",
    );
    expect(requests).not.toContain("https://fonts.gstatic.com/s/lora/cyrillic.woff2");
    expect(faces.map(({ bold, italic }) => ({ bold, italic }))).toEqual([
      { bold: false, italic: false },
      { bold: true, italic: false },
    ]);
    expect(faces[0].rule).toContain('font-family:"Lora"');
    expect(faces[0].rule).toContain("src:url(data:font/woff2;base64,AQID)");
    expect(added).toHaveLength(2);
  });

  it("returns no faces for a family Google does not have", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(new Response("", { status: 400 }))),
    );
    expect(await loadFamily("Nope Sans")).toEqual([]);
  });

  it("retries a family whose fetch failed", async () => {
    const fetch = vi.fn(() => Promise.reject(new TypeError("offline")));
    vi.stubGlobal("fetch", fetch);
    expect(await loadFamily("Retry Me")).toEqual([]);
    expect(await loadFamily("Retry Me")).toEqual([]);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("refuses names that are not plain font names", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(await loadFamily('Lora"}*{x')).toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
  });
});

describe("pickFace", () => {
  const regular = { bold: false, italic: false, rule: "r" };
  const bold = { bold: true, italic: false, rule: "b" };
  it("prefers the exact style, then the same weight", () => {
    expect(pickFace([regular, bold], true, false)).toBe(bold);
    expect(pickFace([regular, bold], true, true)).toBe(bold);
    expect(pickFace([bold], false, false)).toBe(bold);
  });
});

describe("fontRendering", () => {
  it("keeps a loaded family and embeds its face in the slide", () => {
    const presentation = createPresentation();
    const slide = addBlankSlide(presentation);
    const shape = addSlideTextBox(slide, {
      x: inches(0),
      y: inches(0),
      w: inches(1),
      h: inches(1),
      text: "Hello",
    });
    setShapeTextFormat(shape, { font: "Lora" });
    const face = { bold: false, italic: false, rule: "@font-face{}" };
    const rendering = fontRendering(new Map([["Lora", [face]]]));

    const svg = renderSlideToSvg(presentation, slide, rendering.options);

    expect(rendering.seen).toContain("Lora");
    expect(svg).toContain("Lora");
    expect(rendering.css()).toBe("@font-face{}");
    const doc = new DOMParser().parseFromString(
      withFonts(svg, rendering.css()),
      "image/svg+xml",
    );
    expect(doc.documentElement.firstElementChild?.textContent).toBe("@font-face{}");
  });

  it("substitutes a family that did not load", () => {
    const presentation = createPresentation();
    const slide = addBlankSlide(presentation);
    const shape = addSlideTextBox(slide, {
      x: inches(0),
      y: inches(0),
      w: inches(1),
      h: inches(1),
      text: "Hello",
    });
    setShapeTextFormat(shape, { font: "Nope Sans" });
    const rendering = fontRendering(new Map());

    const svg = renderSlideToSvg(presentation, slide, rendering.options);

    expect(rendering.seen).toContain("Nope Sans");
    expect(svg).not.toContain("Nope Sans");
    expect(rendering.css()).toBe("");
  });
});

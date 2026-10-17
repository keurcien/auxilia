import { describe, expect, it } from "vitest";
import {
  addBlankSlide,
  addSlideTextBox,
  createPresentation,
  getShapeId,
  getSlideShapes,
  inches,
} from "@office-kit/pptx";
import { renderSlideToSvg } from "@office-kit/pptx-preview";
import { textBoxes, withoutText } from "./pptx-viewer";

describe("pptx text boxes", () => {
  it("places text shapes as fractions of the slide", () => {
    const presentation = createPresentation();
    const slide = addBlankSlide(presentation);
    addSlideTextBox(slide, {
      x: inches(1),
      y: inches(1),
      w: inches(4),
      h: inches(1),
      text: "Hello",
    });
    const [box, ...rest] = textBoxes(presentation, slide);
    expect(rest).toEqual([]);
    // 16:9 default canvas: 13.333 × 7.5 inches.
    expect(box.left).toBeCloseTo(1 / 13.333, 3);
    expect(box.top).toBeCloseTo(1 / 7.5, 3);
    expect(box.width).toBeCloseTo(4 / 13.333, 3);
    // 18pt default on a 13.333in slide: 18 / (13.333 × 72) of its width.
    expect(parseFloat(String(box.style.fontSize))).toBeCloseTo(
      (18 / (13.333 * 72)) * 100,
      2,
    );
  });
});

describe("in-place editing render", () => {
  it("drops only the edited shape's text", () => {
    const presentation = createPresentation();
    const slide = addBlankSlide(presentation);
    for (const [y, text] of [
      [1, "Edited"],
      [3, "Kept"],
    ] as const)
      addSlideTextBox(slide, {
        x: inches(1),
        y: inches(y),
        w: inches(4),
        h: inches(1),
        text,
      });
    const edited = getShapeId(getSlideShapes(slide)[0]);
    const svg = withoutText(
      renderSlideToSvg(presentation, slide, { textLayout: "svg" }),
      edited,
    );
    expect(svg).not.toContain("Edited");
    expect(svg).toContain("Kept");
  });
});

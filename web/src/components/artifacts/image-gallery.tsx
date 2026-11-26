"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { KeyboardEvent, TouchEvent } from "react";
import Image from "next/image";
import { ChevronLeft, ChevronRight, ImageOff, Loader2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { GalleryImageData, ImageGalleryData } from "@/lib/transcript";

/** Reads one stored preview. The caller decides the route and credentials
 *  (the thread's artifacts, or a public share and its token). */
export type GalleryLoader = (
  imageId: string,
  signal: AbortSignal,
) => Promise<Blob>;

type Slot = { url: string } | { error: string };

const SWIPE_THRESHOLD = 40;
const SWIPE_CLICK_WINDOW = 400;

/** Object URLs for the images actually requested: the gallery asks for the
 *  visible image and its neighbours, never the whole set up front. */
function useGalleryImages(load: GalleryLoader) {
  const [slots, setSlots] = useState<Record<string, Slot>>({});
  const requested = useRef(new Set<string>());
  const controller = useRef<AbortController | null>(null);
  const urls = useRef<string[]>([]);

  useEffect(() => {
    const abort = new AbortController();
    const pending = requested.current;
    const created = urls.current;
    controller.current = abort;
    return () => {
      abort.abort();
      pending.clear();
      for (const url of created) URL.revokeObjectURL(url);
      created.length = 0;
    };
  }, [load]);

  const request = useCallback(
    (image: GalleryImageData | undefined) => {
      const signal = controller.current?.signal;
      if (!image || !signal || requested.current.has(image.id)) return;
      requested.current.add(image.id);
      load(image.id, signal).then(
        (blob) => {
          if (signal.aborted) return;
          const url = URL.createObjectURL(blob);
          urls.current.push(url);
          setSlots((current) => ({ ...current, [image.id]: { url } }));
        },
        (error: unknown) => {
          if (signal.aborted) return;
          setSlots((current) => ({
            ...current,
            [image.id]: {
              error:
                error instanceof Error
                  ? error.message
                  : "This image could not be loaded.",
            },
          }));
        },
      );
    },
    [load],
  );

  const retry = useCallback(
    (image: GalleryImageData) => {
      requested.current.delete(image.id);
      setSlots((current) => {
        const next = { ...current };
        delete next[image.id];
        return next;
      });
      request(image);
    },
    [request],
  );

  return { slots, request, retry };
}

function useSwipe(onSwipe: (step: 1 | -1) => void) {
  const start = useRef<{ x: number; y: number } | null>(null);
  const swipedAt = useRef(0);
  return {
    handlers: {
      onTouchStart: (event: TouchEvent) => {
        const touch = event.touches[0];
        start.current = touch ? { x: touch.clientX, y: touch.clientY } : null;
        swipedAt.current = 0;
      },
      onTouchEnd: (event: TouchEvent) => {
        const origin = start.current;
        const touch = event.changedTouches[0];
        start.current = null;
        if (!origin || !touch) return;
        const dx = touch.clientX - origin.x;
        const dy = touch.clientY - origin.y;
        if (Math.abs(dx) > SWIPE_THRESHOLD && Math.abs(dx) > Math.abs(dy)) {
          swipedAt.current = event.timeStamp;
          onSwipe(dx < 0 ? 1 : -1);
        }
      },
    },
    /** True when a swipe just ended, so the click it may synthesize does not
     *  open the image. A later click, by mouse or tap, still opens it. */
    consumeSwipe: (clickAt: number) => {
      const recent =
        swipedAt.current > 0 && clickAt - swipedAt.current < SWIPE_CLICK_WINDOW;
      swipedAt.current = 0;
      return recent;
    },
  };
}

function formatTakenAt(value: string): string | null {
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(value);
  const date = new Date(dateOnly ? `${value}T00:00:00` : value);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(
    undefined,
    dateOnly
      ? { dateStyle: "long" }
      : { dateStyle: "long", timeStyle: "short" },
  ).format(date);
}

function describeImage(image: GalleryImageData): string | null {
  const parts = [
    image.takenAt ? formatTakenAt(image.takenAt) : null,
    image.location,
  ].filter((part): part is string => Boolean(part));
  return parts.length > 0 ? parts.join(" / ") : null;
}

function altText(image: GalleryImageData, position: number): string {
  return image.caption ?? describeImage(image) ?? `Image ${position}`;
}

function Caption({ image }: { image: GalleryImageData }) {
  const meta = describeImage(image);
  if (!image.caption && !meta) return null;
  return (
    <div className="space-y-0.5 px-3 py-2">
      {image.caption && (
        <p className="text-[12.5px] leading-snug text-foreground">
          {image.caption}
        </p>
      )}
      {meta && <p className="text-[11.5px] text-meta">{meta}</p>}
    </div>
  );
}

function NavButton({
  direction,
  disabled,
  onClick,
}: {
  direction: "previous" | "next";
  disabled: boolean;
  onClick: () => void;
}) {
  const Icon = direction === "previous" ? ChevronLeft : ChevronRight;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-label={direction === "previous" ? "Previous image" : "Next image"}
      className={cn(
        "absolute top-1/2 z-10 flex size-10 -translate-y-1/2 cursor-pointer items-center justify-center rounded-full border border-border bg-card/90 text-foreground shadow-sm transition-opacity hover:bg-card disabled:cursor-default disabled:opacity-35",
        direction === "previous" ? "left-2" : "right-2",
      )}
    >
      <Icon className="size-5" />
    </button>
  );
}

function Frame({
  image,
  position,
  slot,
  onOpen,
  onRetry,
  large,
}: {
  image: GalleryImageData;
  position: number;
  slot: Slot | undefined;
  onOpen?: (clickAt: number) => void;
  onRetry: () => void;
  large?: boolean;
}) {
  if (!slot) {
    return (
      <div className="flex h-full items-center justify-center text-meta">
        <Loader2 className="size-5 animate-spin" aria-hidden />
        <span className="sr-only">Loading image {position}</span>
      </div>
    );
  }
  if ("error" in slot) {
    return (
      <div
        role="alert"
        className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center"
      >
        <ImageOff className="size-5 text-meta" aria-hidden />
        <p className="text-[12.5px] text-subtle">{slot.error}</p>
        <button
          type="button"
          onClick={onRetry}
          className="cursor-pointer whitespace-nowrap rounded-[7px] border border-input px-3 py-1 text-[12px] font-medium text-subtle hover:bg-hover hover:text-foreground"
        >
          Retry
        </button>
      </div>
    );
  }
  const picture = (
    <Image
      unoptimized
      fill
      src={slot.url}
      alt={altText(image, position)}
      sizes={large ? "92vw" : "(max-width: 640px) 100vw, 576px"}
      className="object-contain"
      draggable={false}
    />
  );
  return onOpen ? (
    <button
      type="button"
      onClick={(event) => {
        onOpen(event.timeStamp);
      }}
      aria-label={`Open image ${position} in full size`}
      className="absolute inset-0 cursor-zoom-in"
    >
      {picture}
    </button>
  ) : (
    picture
  );
}

/** A `show_images` result: one image on its own, or a carousel with arrows,
 *  a counter, keyboard and swipe navigation. Clicking opens a larger view. */
export function ImageGallery({
  gallery,
  load,
}: {
  gallery: ImageGalleryData;
  load: GalleryLoader;
}) {
  const { images } = gallery;
  const count = images.length;
  const [index, setIndex] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const { slots, request, retry } = useGalleryImages(load);
  const position = Math.min(index, count - 1);
  const current = images[position];
  const multiple = count > 1;

  useEffect(() => {
    request(images[position]);
    request(images[position + 1]);
    request(images[position - 1]);
  }, [images, position, request]);

  const go = useCallback(
    (step: 1 | -1) => {
      setIndex((value) => Math.max(0, Math.min(count - 1, value + step)));
    },
    [count],
  );
  const inline = useSwipe(go);
  const enlarged = useSwipe(go);

  const onKeyDown = (event: KeyboardEvent) => {
    if (!multiple) return;
    if (event.key === "ArrowLeft") {
      event.preventDefault();
      go(-1);
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      go(1);
    }
  };

  if (!current) return null;
  const label = gallery.title ?? (multiple ? "Image gallery" : "Image");
  const slot = slots[current.id];
  const controls = multiple && (
    <>
      <NavButton
        direction="previous"
        disabled={position === 0}
        onClick={() => {
          go(-1);
        }}
      />
      <NavButton
        direction="next"
        disabled={position === count - 1}
        onClick={() => {
          go(1);
        }}
      />
      <span
        aria-live="polite"
        className="absolute right-2 bottom-2 z-10 rounded-full bg-black/60 px-2 py-0.5 font-mono text-[11px] tabular-nums text-white"
      >
        {position + 1} / {count}
      </span>
    </>
  );

  return (
    <>
      <section
        aria-roledescription={multiple ? "carousel" : undefined}
        aria-label={label}
        tabIndex={multiple ? 0 : undefined}
        onKeyDown={onKeyDown}
        className="my-2 w-full max-w-xl overflow-hidden rounded-[10px] border border-border bg-card outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
      >
        {gallery.title && (
          <p className="px-3 pt-2.5 pb-2 text-[12.5px] font-semibold text-foreground">
            {gallery.title}
          </p>
        )}
        <div
          className="relative h-[min(55vh,340px)] touch-pan-y bg-hover sm:h-[420px]"
          {...inline.handlers}
        >
          <Frame
            image={current}
            position={position + 1}
            slot={slot}
            onOpen={(clickAt) => {
              if (!inline.consumeSwipe(clickAt)) setExpanded(true);
            }}
            onRetry={() => {
              retry(current);
            }}
          />
          {controls}
        </div>
        <Caption image={current} />
      </section>
      <Dialog open={expanded} onOpenChange={setExpanded}>
        <DialogContent
          onKeyDown={onKeyDown}
          className="max-w-[calc(100%-1rem)] gap-2 p-3 sm:max-w-[min(92vw,1100px)]"
        >
          <DialogTitle className="sr-only">{label}</DialogTitle>
          <DialogDescription className="sr-only">
            {altText(current, position + 1)}
          </DialogDescription>
          <div
            className="relative mt-8 h-[min(78dvh,900px)] touch-pan-y bg-hover"
            {...enlarged.handlers}
          >
            <Frame
              image={current}
              position={position + 1}
              slot={slot}
              large
              onRetry={() => {
                retry(current);
              }}
            />
            {controls}
          </div>
          <Caption image={current} />
        </DialogContent>
      </Dialog>
    </>
  );
}

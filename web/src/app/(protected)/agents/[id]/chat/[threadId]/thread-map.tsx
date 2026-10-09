"use client";

import { memo, useMemo } from "react";
import type { BaseMessage } from "@langchain/core/messages";
import { isHumanMessage } from "@langchain/core/messages";

import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import { cn } from "@/lib/utils";

type ThreadMapProps = {
  messages: BaseMessage[];
};

type PromptMarker = {
  anchorId: string;
  index: number;
  text: string;
};

export const threadMapAnchor = (messageIndex: number) =>
  `thread-prompt-${messageIndex}`;

export const ThreadMap = memo(function ThreadMap({
  messages,
}: ThreadMapProps) {
  const prompts = useMemo<PromptMarker[]>(
    () =>
      messages.flatMap((message, messageIndex) => {
        if (!isHumanMessage(message) || message.name === "host") return [];
        return [
          {
            anchorId: threadMapAnchor(messageIndex),
            index: messageIndex,
            text: message.text.trim() || "Prompt with attachments",
          },
        ];
      }),
    [messages],
  );

  // A single prompt has nowhere to jump to: no map until there are two.
  if (prompts.length < 2) return null;

  const jumpTo = (anchorId: string) => {
    const target = document.getElementById(anchorId);
    if (!target) return;
    target.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "center",
    });
  };

  return (
    <nav
      aria-label="Conversation prompt map"
      className="pointer-events-none absolute right-3 top-1/2 z-20 hidden -translate-y-1/2 lg:block xl:right-5"
    >
      <div className="pointer-events-auto max-h-[56vh] overflow-y-auto py-2 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        <div className="relative flex min-h-10 w-11 flex-col items-end gap-1.5 py-1">
          <div
            aria-hidden="true"
            className="absolute bottom-0 right-0 top-0 w-px bg-gradient-to-b from-transparent via-border to-transparent"
          />
          {prompts.map((prompt, promptIndex) => {
            const isMajor =
              promptIndex === 0 ||
              promptIndex === prompts.length - 1 ||
              (promptIndex + 1) % 5 === 0;

            return (
              <HoverCard
                key={`${prompt.anchorId}-${prompt.index}`}
                openDelay={100}
                closeDelay={60}
              >
                <HoverCardTrigger asChild>
                  <button
                    type="button"
                    aria-label={`Go to prompt ${promptIndex + 1}: ${prompt.text}`}
                    onClick={() => {
                      jumpTo(prompt.anchorId);
                    }}
                    className="group relative z-10 flex h-3 w-11 cursor-pointer items-center justify-end outline-none"
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "block h-px origin-right rounded-full bg-meta/55 transition-[width,height,background-color] duration-150 ease-out",
                        isMajor ? "w-4" : "w-2.5",
                        "group-hover:h-0.5 group-hover:w-7 group-hover:bg-petrol",
                        "group-focus-visible:h-0.5 group-focus-visible:w-7 group-focus-visible:bg-petrol",
                      )}
                    />
                  </button>
                </HoverCardTrigger>
                <HoverCardContent
                  side="left"
                  align="center"
                  sideOffset={12}
                  className="pointer-events-none w-72 rounded-md border-hairline bg-card/95 p-3 shadow-raised backdrop-blur-md"
                >
                  <p className="line-clamp-6 whitespace-pre-wrap text-[12.5px] font-medium leading-[1.55] text-foreground">
                    {prompt.text}
                  </p>
                </HoverCardContent>
              </HoverCard>
            );
          })}
        </div>
      </div>
    </nav>
  );
});

"use client";

import { AlarmClock } from "lucide-react";
import { useRouter } from "next/navigation";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { formatRunAt } from "@/lib/triggers/schedule";
import { AgentAvatar } from "@/components/ui/agent-avatar";

export function ChatHeader() {
  const router = useRouter();
  const {
    agentName,
    agentEmoji,
    agentColor,
    triggerId,
    triggerName,
    triggerRunAt,
  } = useChatHeaderStore();

  // Trigger-fired thread: trigger name + firing time behind an alarm clock.
  if (triggerName) {
    return (
      <div className="flex h-14 shrink-0 items-center justify-center gap-2 px-5 font-[family-name:var(--font-dm-sans)] text-[14px]">
        <div className="flex items-center justify-center shrink-0 size-7 rounded-full bg-[#EDF4F0] dark:bg-emerald-950/40">
          <AlarmClock className="size-3.5 text-[#3D8B63] dark:text-emerald-400" />
        </div>
        {triggerId ? (
          <button
            type="button"
            onClick={() => {
              router.push(`/triggers/${triggerId}`);
            }}
            className="cursor-pointer font-semibold text-[#1E2D28] dark:text-foreground rounded-sm transition-colors hover:text-[#3D8B63] dark:hover:text-emerald-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#3D8B63]/40"
          >
            {triggerName}
          </button>
        ) : (
          <span className="font-semibold text-[#1E2D28] dark:text-foreground">
            {triggerName}
          </span>
        )}
        {triggerRunAt && (
          <>
            <span className="text-[#C4D0CA] dark:text-white/20">/</span>
            <span className="font-medium text-[#4A5B53] dark:text-white/70">
              {formatRunAt(
                triggerRunAt,
                Intl.DateTimeFormat().resolvedOptions().timeZone,
              )}
            </span>
          </>
        )}
      </div>
    );
  }

  if (!agentName) return null;

  return (
    <div className="flex h-14 shrink-0 items-center justify-center gap-2 px-5">
      <AgentAvatar color={agentColor} emoji={agentEmoji} size="xs" />
      <span className="font-[family-name:var(--font-dm-sans)] font-semibold text-[14px] text-[#1E2D28] dark:text-foreground">
        {agentName}
      </span>
    </div>
  );
}

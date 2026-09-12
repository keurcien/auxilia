import type { BaseMessage } from "@langchain/core/messages";
import { isAIMessage, isHumanMessage } from "@langchain/core/messages";

import { getReasoning } from "./message";
import type { ToolCallView } from "./tool-calls";

export type ChainStepData =
  | { kind: "reasoning"; id: string; messageId: string; text: string }
  | { kind: "tool"; id: string; tc: ToolCallView };

/**
 * Group a turn's work into chains of steps: each AI message's reasoning and
 * tool calls, in order. Consecutive AI messages without text extend one chain,
 * owned by the first of them; an AI message with text closes the chain (its
 * own reasoning still lands in it, above the text), a human turn resets it.
 * Returns `owner message id → steps`.
 */
export function groupChains(
  messages: readonly BaseMessage[],
  toolCalls: readonly ToolCallView[],
): Map<string, ChainStepData[]> {
  const callsByMessage = new Map<string, ToolCallView[]>();
  for (const tc of toolCalls) {
    if (!tc.messageId) continue;
    const list = callsByMessage.get(tc.messageId);
    if (list) list.push(tc);
    else callsByMessage.set(tc.messageId, [tc]);
  }

  const chains = new Map<string, ChainStepData[]>();
  let owner: string | null = null;
  for (const m of messages) {
    if (isHumanMessage(m)) {
      owner = null;
      continue;
    }
    if (!isAIMessage(m)) continue;
    const hasText = m.text.trim().length > 0;
    if (!m.id) {
      // Nothing to attach steps to, but an answer still closes the chain.
      if (hasText) owner = null;
      continue;
    }
    const reasoning = getReasoning(m);
    const steps: ChainStepData[] = [
      ...(reasoning
        ? [{ kind: "reasoning" as const, id: `${m.id}-reasoning`, messageId: m.id, text: reasoning }]
        : []),
      ...(callsByMessage.get(m.id) ?? []).map((tc) => ({ kind: "tool" as const, id: tc.id, tc })),
    ];
    if (steps.length > 0) {
      if (owner == null) {
        owner = m.id;
        chains.set(m.id, steps);
      } else {
        chains.get(owner)?.push(...steps);
      }
    }
    if (hasText) owner = null;
  }
  return chains;
}

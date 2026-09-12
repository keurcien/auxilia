/**
 * Pure views over the `@langchain/react` stream: the message log is the one
 * source of truth (`stream.messages` / `useMessages(stream, subagent)`), and
 * everything the conversation renders — tool cards, chains, attachments,
 * reasoning — is derived from it here. The `tools` channel (`stream.toolCalls`
 * / `useToolCalls`) only overlays what a live ToolMessage cannot carry yet:
 * status, error text and the MCP artifact.
 *
 * No React, no stores: payloads in, views out. Split by concern —
 * `message.ts` (one message), `tool-calls.ts` (call ↔ result pairing and step
 * state), `interrupts.ts` (HITL namespaces), `chains.ts` (turn grouping).
 */

export * from "./message";
export * from "./tool-calls";
export * from "./interrupts";
export * from "./chains";

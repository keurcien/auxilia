import type { Interrupt } from "@langchain/langgraph-sdk";

/** `stream.interrupts` mirrors every namespace's pending interrupt; the root
 *  one drives the root chain's approval UI, the nested ones belong to the
 *  subagent cards (`findSubagentInterrupt`). */
export function splitInterrupts(interrupts: readonly Interrupt[]): {
  root: Interrupt | null;
  nested: Interrupt[];
} {
  let root: Interrupt | null = null;
  const nested: Interrupt[] = [];
  for (const interrupt of interrupts) {
    if (isRootNamespace(interrupt.namespace)) root ??= interrupt;
    else nested.push(interrupt);
  }
  return { root, nested };
}

const isRootNamespace = (namespace: readonly string[] | undefined) =>
  namespace == null || namespace.length === 0;

export const sameNamespace = (
  a: readonly string[] | undefined,
  b: readonly string[],
) => a != null && a.length === b.length && a.join("|") === b.join("|");

/**
 * Whether an interrupt was raised inside this subagent.
 *
 * Live, the backend stamps the subagent's execution namespace
 * (`tools:<pregel task id>`) on `input.requested`, and the SDK binds the same
 * namespace onto the discovery snapshot as the subagent streams. A page that
 * hydrates instead rebuilds the snapshot under the SDK's discovery key,
 * `tools:<tool_call_id>`, and the backend addresses a hydrated interrupt with
 * that key — so both are accepted, and nothing is matched by content (two
 * siblings calling the same tool with the same arguments would otherwise
 * claim one interrupt).
 */
export function claimsInterrupt(
  interrupt: Interrupt,
  subagent: { id: string; namespace: readonly string[] },
): boolean {
  return (
    sameNamespace(interrupt.namespace, subagent.namespace) ||
    sameNamespace(interrupt.namespace, [`tools:${subagent.id}`])
  );
}

/** The pending interrupt raised inside one subagent, if any. */
export function findSubagentInterrupt(
  nested: readonly Interrupt[],
  subagent: { id: string; namespace: readonly string[] },
): Interrupt | null {
  return nested.find((interrupt) => claimsInterrupt(interrupt, subagent)) ?? null;
}

/** The HITL middleware only hangs the tool calls named in the interrupt's
 *  `action_requests`; sibling calls in the same turn run on resume. */
export function extractHitlToolNames(value: unknown): Set<string> | null {
  if (!value || typeof value !== "object") return null;
  const requests = (value as { action_requests?: unknown }).action_requests;
  if (!Array.isArray(requests)) return null;
  return new Set(
    requests
      .map((r: { name?: unknown } | null) => r?.name)
      .filter((n): n is string => typeof n === "string"),
  );
}

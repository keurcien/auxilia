import type { Interrupt } from "@langchain/langgraph-sdk";

export type HeldInterrupts = { key: string; list: readonly Interrupt[] };

/** Identity of a set of interrupts: their ids and namespaces, in order. */
export function interruptsKey(interrupts: readonly Interrupt[]): string {
	return interrupts
		.map((i) => `${i.id ?? ""}@${(i.namespace ?? []).join("/")}`)
		.join(",");
}

/**
 * Keep the previous interrupt list while its key is unchanged. `stream.interrupts`
 * is a fresh array on every store tick; holding identity keeps the derived
 * root/nested split (and every memo below it) stable between ticks.
 */
export function holdInterrupts(
	prev: HeldInterrupts,
	next: readonly Interrupt[],
): HeldInterrupts {
	const key = interruptsKey(next);
	return key === prev.key ? prev : { key, list: next };
}

export const EMPTY_HELD: HeldInterrupts = { key: "", list: [] };

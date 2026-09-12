import type { Interrupt } from "@langchain/langgraph-sdk";

export type HeldInterrupts = { key: string; list: readonly Interrupt[] };

/**
 * Identity of a set of interrupts: their ids and namespaces, in order. An
 * interrupt without an id (a checkpoint written before ids were stamped) is
 * keyed by its value instead, so two id-less entries in one namespace are not
 * mistaken for each other and a changed pending request is not held stale.
 */
export function interruptsKey(interrupts: readonly Interrupt[]): string {
	return interrupts
		.map((i) => `${i.id ?? valueKey(i.value)}@${(i.namespace ?? []).join("/")}`)
		.join(",");
}

function valueKey(value: unknown): string {
	try {
		return `~${JSON.stringify(value) ?? ""}`;
	} catch {
		return "~";
	}
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

import { describe, expect, it } from "vitest";
import type { Interrupt } from "@langchain/langgraph-sdk";

import { EMPTY_HELD, holdInterrupts, interruptsKey } from "./interrupt-hold";

const intr = (id: string | undefined, namespace?: string[], value: unknown = {}): Interrupt =>
	({ id, value, namespace }) as Interrupt;

describe("holdInterrupts", () => {
	it("keeps the previous list while ids and namespaces are unchanged", () => {
		const held = holdInterrupts(EMPTY_HELD, [intr("i1"), intr("i2", ["tools:x"])]);
		const again = holdInterrupts(held, [intr("i1"), intr("i2", ["tools:x"])]);
		expect(again).toBe(held);
	});

	it("swaps when an interrupt appears, disappears or moves namespace", () => {
		const held = holdInterrupts(EMPTY_HELD, [intr("i1")]);
		expect(holdInterrupts(held, [])).not.toBe(held);
		expect(holdInterrupts(held, [intr("i1"), intr("i2")])).not.toBe(held);
		expect(holdInterrupts(held, [intr("i1", ["tools:y"])])).not.toBe(held);
	});

	it("holds the same reference while ids and namespaces are unchanged, even if values differ", () => {
		const held = holdInterrupts(EMPTY_HELD, [intr("i1", undefined, { action_requests: [{ name: "a" }] })]);
		const again = holdInterrupts(held, [intr("i1", undefined, { action_requests: [{ name: "b" }] })]);
		expect(again).toBe(held);
		expect(again.list[0].value).toEqual({ action_requests: [{ name: "a" }] });
	});

	it("keys id-less interrupts by value so a changed pending request is not held stale", () => {
		const held = holdInterrupts(EMPTY_HELD, [intr(undefined, [], { action_requests: [{ name: "a" }] })]);
		const changed = holdInterrupts(held, [intr(undefined, [], { action_requests: [{ name: "b" }] })]);
		expect(changed).not.toBe(held);
		const two = holdInterrupts(EMPTY_HELD, [intr(undefined, [], { n: 1 }), intr(undefined, [], { n: 2 })]);
		const swapped = holdInterrupts(two, [intr(undefined, [], { n: 2 }), intr(undefined, [], { n: 1 })]);
		expect(swapped).not.toBe(two);
	});

	it("keys on id and namespace", () => {
		expect(interruptsKey([intr("a"), intr("b", ["n", "m"])])).toBe("a@,b@n/m");
	});
});

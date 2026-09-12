import { describe, expect, it } from "vitest";
import type { Interrupt } from "@langchain/langgraph-sdk";

import { EMPTY_HELD, holdInterrupts, interruptsKey } from "./interrupt-hold";

const intr = (id: string, namespace?: string[]): Interrupt =>
	({ id, value: {}, namespace }) as Interrupt;

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

	it("keys on id and namespace only", () => {
		expect(interruptsKey([intr("a"), intr("b", ["n", "m"])])).toBe("a@,b@n/m");
	});
});

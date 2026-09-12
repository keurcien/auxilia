import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { submitPendingAfterHydration } from "./pending-message";

beforeEach(() => {
	vi.useFakeTimers();
});
afterEach(() => {
	vi.useRealTimers();
});

describe("submitPendingAfterHydration", () => {
	it("submits once hydration settles, before the cap", async () => {
		let resolve!: () => void;
		const hydration = new Promise<void>((r) => {
			resolve = r;
		});
		const submit = vi.fn();
		const done = submitPendingAfterHydration(hydration, submit, { capMs: 4_000 });
		await vi.advanceTimersByTimeAsync(1_000);
		expect(submit).not.toHaveBeenCalled();
		resolve();
		await done;
		expect(submit).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(10_000);
		expect(submit).toHaveBeenCalledTimes(1);
	});

	it("submits at the cap when hydration hangs", async () => {
		const submit = vi.fn();
		const done = submitPendingAfterHydration(new Promise(() => {}), submit, { capMs: 4_000 });
		await vi.advanceTimersByTimeAsync(3_999);
		expect(submit).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);
		await done;
		expect(submit).toHaveBeenCalledTimes(1);
	});

	it("a failed hydration still submits — exactly once", async () => {
		const submit = vi.fn();
		await submitPendingAfterHydration(Promise.reject(new Error("no snapshot")), submit);
		expect(submit).toHaveBeenCalledTimes(1);
	});
});

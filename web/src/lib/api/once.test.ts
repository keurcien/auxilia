import { describe, expect, it, vi } from "vitest";

import { createOnce } from "./once";

function deferred<T>() {
	let resolve!: (v: T) => void;
	let reject!: (e: unknown) => void;
	const promise = new Promise<T>((res, rej) => {
		resolve = res;
		reject = rej;
	});
	return { promise, resolve, reject };
}

describe("createOnce", () => {
	it("shares one in-flight load between concurrent run() calls", async () => {
		const d = deferred<number>();
		const load = vi.fn(() => d.promise);
		const once = createOnce(load);
		const a = once.run();
		const b = once.run();
		expect(load).toHaveBeenCalledTimes(1);
		d.resolve(1);
		expect(await Promise.all([a, b])).toEqual([1, 1]);
	});

	it("loads again once the previous load settled", async () => {
		const load = vi.fn().mockResolvedValueOnce(1).mockResolvedValueOnce(2);
		const once = createOnce(load);
		expect(await once.run()).toBe(1);
		expect(await once.run()).toBe(2);
		expect(load).toHaveBeenCalledTimes(2);
	});

	it("refresh() waits for the in-flight load, then loads again — even after a failure", async () => {
		const first = deferred<number>();
		const load = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(2);
		const once = createOnce(load);
		const a = once.run().catch(() => "failed");
		const b = once.refresh();
		expect(load).toHaveBeenCalledTimes(1);
		first.reject(new Error("boom"));
		expect(await a).toBe("failed");
		expect(await b).toBe(2);
		expect(load).toHaveBeenCalledTimes(2);
	});

	it("a rejected load does not poison the next run()", async () => {
		const load = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValueOnce(3);
		const once = createOnce(load);
		await expect(once.run()).rejects.toThrow("x");
		expect(await once.run()).toBe(3);
	});
});

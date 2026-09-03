import { act, renderHook } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useThrottledValue } from "./use-throttled-value";

describe("useThrottledValue", () => {
	beforeEach(() => {
		vi.useFakeTimers();
	});
	afterEach(() => {
		vi.useRealTimers();
	});

	it("follows the value under StrictMode, at most once per interval", () => {
		const { result, rerender } = renderHook(
			({ value }: { value: string[] }) => useThrottledValue(value, 60),
			{ initialProps: { value: [] as string[] }, wrapper: StrictMode },
		);
		expect(result.current).toEqual([]);

		rerender({ value: ["a"] });
		act(() => {
			vi.advanceTimersByTime(60);
		});
		expect(result.current).toEqual(["a"]);

		rerender({ value: ["a", "b"] });
		rerender({ value: ["a", "b", "c"] });
		act(() => {
			vi.advanceTimersByTime(59);
		});
		expect(result.current).toEqual(["a"]);
		act(() => {
			vi.advanceTimersByTime(1);
		});
		expect(result.current).toEqual(["a", "b", "c"]);
	});
});

import { useEffect, useRef, useState } from "react";

/**
 * Trailing throttle: re-emits `value` at most once per `intervalMs`. Bounds
 * how often the memoized conversation tree rebuilds under token streaming
 * (the stream store ticks once per SSE macrotask, i.e. per token).
 */
export function useThrottledValue<T>(value: T, intervalMs = 60): T {
	const [throttled, setThrottled] = useState(value);
	const box = useRef({
		latest: value,
		lastEmit: 0,
		timer: null as ReturnType<typeof setTimeout> | null,
	});

	useEffect(() => {
		const s = box.current;
		s.latest = value;
		if (s.timer != null) return;
		const wait = Math.max(0, intervalMs - (performance.now() - s.lastEmit));
		s.timer = setTimeout(() => {
			s.timer = null;
			s.lastEmit = performance.now();
			setThrottled(s.latest);
		}, wait);
	}, [value, intervalMs]);

	useEffect(() => {
		const s = box.current;
		return () => {
			// Reset the handle too: StrictMode re-runs effects after this cleanup,
			// and a stale handle would make the emit effect above bail forever.
			if (s.timer != null) clearTimeout(s.timer);
			s.timer = null;
		};
	}, []);

	return throttled;
}

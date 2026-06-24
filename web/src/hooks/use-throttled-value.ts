import { useEffect, useLayoutEffect, useRef, useState } from "react";

const getCurrentTime = () =>
	typeof performance !== "undefined" ? performance.now() : Date.now();

export function useThrottledValue<T>(value: T, intervalMs = 60): T {
	const [throttled, setThrottled] = useState(value);
	const lastEmitRef = useRef(0);
	const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const latestRef = useRef(value);

	useLayoutEffect(() => {
		latestRef.current = value;
	}, [value]);

	useEffect(() => {
		const now = getCurrentTime();
		const elapsed = now - lastEmitRef.current;

		if (timerRef.current != null) {
			if (elapsed < intervalMs) return;
			clearTimeout(timerRef.current);
		}

		const delay = Math.max(intervalMs - elapsed, 0);
		timerRef.current = setTimeout(() => {
			timerRef.current = null;
			lastEmitRef.current = getCurrentTime();
			setThrottled(latestRef.current);
		}, delay);
	}, [value, intervalMs]);

	useEffect(() => {
		return () => {
			if (timerRef.current != null) clearTimeout(timerRef.current);
		};
	}, []);

	return throttled;
}

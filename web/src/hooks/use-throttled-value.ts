import { useEffect, useRef, useState } from "react";

export function useThrottledValue<T>(value: T, intervalMs = 60): T {
	const [throttled, setThrottled] = useState(value);
	const lastEmitRef = useRef(0);
	const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const latestRef = useRef(value);

	latestRef.current = value;

	useEffect(() => {
		const now =
			typeof performance !== "undefined" ? performance.now() : Date.now();
		const elapsed = now - lastEmitRef.current;

		if (elapsed >= intervalMs) {
			lastEmitRef.current = now;
			setThrottled(value);
			return;
		}

		if (timerRef.current != null) return;

		timerRef.current = setTimeout(() => {
			timerRef.current = null;
			lastEmitRef.current =
				typeof performance !== "undefined" ? performance.now() : Date.now();
			setThrottled(latestRef.current);
		}, intervalMs - elapsed);
	}, [value, intervalMs]);

	useEffect(() => {
		return () => {
			if (timerRef.current != null) clearTimeout(timerRef.current);
		};
	}, []);

	return throttled;
}

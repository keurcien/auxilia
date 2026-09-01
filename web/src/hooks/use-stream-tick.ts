import { useEffect, useRef, useState } from "react";

/**
 * A counter that bumps at most once per `intervalMs`, and only after the
 * owning component rendered for some other reason.
 *
 * Purpose: the LangGraph SDK notifies its subscriber on every SSE event, but
 * some of those notifications change nothing a memoized child receives by
 * prop — subagent token streams only bump an internal version counter.
 * Passing this tick as a prop lets a memoized conversation body follow that
 * activity at a bounded rate (~16Hz) instead of re-rendering per token.
 *
 * The tick's own state update triggers one render, which must not re-arm the
 * timer (that would loop at 16Hz forever, even when idle) — `skipRef` marks
 * that render so the effect ignores it.
 */
export function useStreamTick(intervalMs = 60): number {
	const [tick, setTick] = useState(0);
	const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const skipRef = useRef(false);

	// No dependency array on purpose: any render of the owner (i.e. any SDK
	// notification) schedules a trailing tick unless one is already pending.
	useEffect(() => {
		if (skipRef.current) {
			skipRef.current = false;
			return;
		}
		if (timerRef.current != null) return;
		timerRef.current = setTimeout(() => {
			timerRef.current = null;
			skipRef.current = true;
			setTick((t) => t + 1);
		}, intervalMs);
	});

	useEffect(() => {
		return () => {
			if (timerRef.current != null) clearTimeout(timerRef.current);
		};
	}, []);

	return tick;
}

"use client";

import { useEffect, useMemo } from "react";
import { api } from "@/lib/api/client";
import { ActiveRun, RunTerminalStatus } from "@/types/runs";
import { Thread } from "@/types/threads";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";

const ACTIVE_POLL_MS = 5_000;
const WATCH_POLL_MS = 15_000;
/** Keep watching for this long after a trigger thread appears. */
const RECENT_TRIGGER_WINDOW_MS = 10 * 60 * 1000;
/** Padding on the recently-finished window, absorbing request latency and
 * server/client clock drift. */
const RECENT_MARGIN_S = 30;
/** Backend cap on `recent_seconds` (tab hidden longer than this misses
 * outcomes until the next `fetchThreads`). */
const MAX_RECENT_S = 3600;

/** Epoch ms of the last successful poll — sizes the next poll's
 * recently-finished window so no terminal transition falls between polls. */
let lastPolledAt: number | null = null;

function isInFlight(run: ActiveRun): boolean {
	return run.status === "pending" || run.status === "running";
}

/** Stamp freshly-observed run outcomes where the UI reads them (sidebar
 * badge, trigger run history). Later entries win — the poll response is
 * ordered by `updatedAt`, so this keeps the latest outcome per thread. */
function applyFinishedRuns(runs: ActiveRun[]): void {
	const latestByThread = new Map<string, RunTerminalStatus>();
	for (const run of runs) {
		latestByThread.set(run.threadId, run.status as RunTerminalStatus);
	}
	for (const [threadId, status] of latestByThread) {
		useThreadsStore.getState().setLastRunStatus(threadId, status);
		useTriggerRunsStore.getState().setRunStatus(threadId, status);
	}
}

async function pollActiveRuns(): Promise<void> {
	const polledAt = Date.now();
	const recentSeconds = Math.min(
		lastPolledAt === null
			? RECENT_MARGIN_S
			: Math.ceil((polledAt - lastPolledAt) / 1000) + RECENT_MARGIN_S,
		MAX_RECENT_S,
	);
	const response = await api.get<ActiveRun[]>("/runs/active", {
		params: { recentSeconds },
	});
	lastPolledAt = polledAt;
	applyFinishedRuns(response.data.filter((run) => !isInFlight(run)));
	useActiveRunsStore.getState().setConfirmed(
		response.data.filter(isInFlight).map((run) => run.threadId),
		polledAt,
	);
}

function storeHasActiveRuns(): boolean {
	const state = useActiveRunsStore.getState();
	return (
		state.confirmedThreadIds.length > 0 ||
		Object.keys(state.optimisticMarkedAt).length > 0
	);
}

/**
 * Thread ids that currently have an in-flight run — client-side marks
 * (instant, via `markThreadRunning`) merged with the aggregate
 * `GET /runs/active` poll (one request regardless of thread count).
 *
 * Polls once on mount to catch runs started elsewhere (invoke API,
 * scheduled firings), then only while there is a reason to — a client
 * mark, a fresh trigger thread, or a known active run — only while the
 * tab is visible, backing off when idle.
 *
 * Each poll also asks for runs that finished since the previous one and
 * stamps their outcome into the threads / trigger-runs stores, so error
 * and success states surface without a threads refetch.
 */
export function useActiveRunThreadIds(threads: Thread[]): Set<string> {
	const confirmedThreadIds = useActiveRunsStore(
		(state) => state.confirmedThreadIds,
	);
	const optimisticMarkedAt = useActiveRunsStore(
		(state) => state.optimisticMarkedAt,
	);
	const pollEpoch = useActiveRunsStore((state) => state.pollEpoch);

	const hasActiveRuns =
		confirmedThreadIds.length > 0 ||
		Object.keys(optimisticMarkedAt).length > 0;
	// Pure in render; compared against the clock inside the effect only.
	const latestTriggerThreadAt = useMemo(
		() =>
			threads.reduce(
				(latest, thread) =>
					thread.source === "trigger"
						? Math.max(latest, new Date(thread.createdAt).getTime())
						: latest,
				0,
			),
		[threads],
	);

	// One poll at page load: surfaces runs this client didn't start.
	useEffect(() => {
		pollActiveRuns().catch((error: unknown) => {
			console.error("Error polling active runs:", error);
		});
	}, []);

	useEffect(() => {
		const inWatchWindow = () =>
			Date.now() - latestTriggerThreadAt < RECENT_TRIGGER_WINDOW_MS;
		if (!hasActiveRuns && !inWatchWindow()) return;

		let cancelled = false;
		let timer: ReturnType<typeof setTimeout> | undefined;

		const schedule = () => {
			timer = setTimeout(
				() => {
					void poll();
				},
				storeHasActiveRuns() ? ACTIVE_POLL_MS : WATCH_POLL_MS,
			);
		};

		const poll = async () => {
			if (cancelled) return;
			if (document.visibilityState === "hidden") {
				schedule();
				return;
			}
			try {
				await pollActiveRuns();
			} catch (error) {
				console.error("Error polling active runs:", error);
			}
			// Keep going only while something is (or may be) running.
			if (!cancelled && (storeHasActiveRuns() || inWatchWindow())) {
				schedule();
			}
		};

		const handleVisibility = () => {
			if (document.visibilityState === "visible") {
				clearTimeout(timer);
				void poll();
			}
		};

		// pollEpoch in the deps re-runs this effect the moment a run is
		// marked client-side, so the server state refreshes immediately.
		void poll();
		document.addEventListener("visibilitychange", handleVisibility);
		return () => {
			cancelled = true;
			clearTimeout(timer);
			document.removeEventListener("visibilitychange", handleVisibility);
		};
	}, [hasActiveRuns, latestTriggerThreadAt, pollEpoch]);

	// Pure union — expired optimistic marks are pruned by the store on
	// every poll, not at render time.
	return useMemo(() => {
		const ids = new Set(confirmedThreadIds);
		for (const threadId of Object.keys(optimisticMarkedAt)) {
			ids.add(threadId);
		}
		return ids;
	}, [confirmedThreadIds, optimisticMarkedAt]);
}

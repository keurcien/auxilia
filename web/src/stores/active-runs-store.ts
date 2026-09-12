import { create } from "zustand";
import type { Run, RunTerminalStatus } from "@/types/runs";
import { useThreadsStore } from "@/stores/threads-store";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";

/** How long an optimistic mark survives without server confirmation. */
const OPTIMISTIC_RUN_TTL_MS = 30_000;
/** Padding on the recently-finished window, absorbing request latency and
 * server/client clock drift. */
export const RECENT_MARGIN_S = 30;
/** Backend cap on `recent_seconds`; a gap wider than this (tab hidden for
 * over an hour) falls back to a full threads refetch instead. */
export const MAX_RECENT_S = 3600;

/** A poll in progress: the ticket `applyPollResult` checks before applying. */
export interface PollTicket {
	seq: number;
	polledAt: number;
	/** `recent_seconds` to ask for: the gap since the last applied poll, padded. */
	recentSeconds: number;
	/** The gap exceeded the backend cap — refetch the thread list instead of
	 * relying on the recently-finished window. */
	refetchThreads: boolean;
}

/** Size the recently-finished window so no terminal transition can fall
 * between two polls. Pure; `now` and `lastPolledAt` are epoch ms. */
export function recentWindow(
	lastPolledAt: number | null,
	now: number,
): Pick<PollTicket, "recentSeconds" | "refetchThreads"> {
	const elapsedSeconds =
		lastPolledAt === null ? 0 : Math.max(0, Math.ceil((now - lastPolledAt) / 1000));
	const padded = elapsedSeconds + RECENT_MARGIN_S;
	return {
		recentSeconds: Math.min(padded, MAX_RECENT_S),
		refetchThreads: padded > MAX_RECENT_S,
	};
}

export function isInFlight(run: Run): boolean {
	return run.status === "pending" || run.status === "running";
}

interface ActiveRunsState {
	/** Thread ids confirmed in-flight by the last `GET /runs/active` poll. */
	confirmedThreadIds: string[];
	/** Optimistically marked thread ids -> marked-at epoch ms. Shown as
	 * running immediately, until a later poll confirms or supersedes them. */
	optimisticMarkedAt: Record<string, number>;
	/** Bumped by `markThreadRunning` so the poller refreshes immediately. */
	pollEpoch: number;
	/** Epoch ms of the last *applied* poll — sizes the next poll's window. */
	lastPolledAt: number | null;
	/** Epoch ms of the first poll attempted since the last applied one, so a
	 * run of failed polls still widens the next successful window. */
	pendingSince: number | null;
	/** Monotonic poll counter — a superseded (older, still in-flight) poll's
	 * response is discarded so it can't overwrite fresher state. */
	pollSeq: number;
	/** Show a thread as running right now (run just started client-side). */
	markThreadRunning: (threadId: string) => void;
	/** Ask the poller to refresh now (e.g. a stream just finished). */
	requestPoll: () => void;
	/** Claim a poll: bumps the sequence and sizes the window. */
	beginPoll: (now?: number) => PollTicket;
	/** Apply a poll response — unless a newer poll has begun since. Stamps
	 * finished runs where the UI reads them (sidebar badge, trigger run
	 * history) and replaces the confirmed in-flight set. */
	applyPollResult: (ticket: PollTicket, runs: Run[]) => void;
	/** Record the confirmed in-flight set; prunes optimistic marks older than the poll. */
	setConfirmed: (threadIds: string[], polledAt: number) => void;
}

/** Later entries win — the poll response is ordered by `updatedAt`, so this
 * keeps the latest outcome per thread. */
function applyFinishedRuns(runs: Run[]): void {
	const latestByThread = new Map<string, RunTerminalStatus>();
	for (const run of runs) {
		if (isInFlight(run)) continue;
		latestByThread.set(run.threadId, run.status as RunTerminalStatus);
	}
	for (const [threadId, status] of latestByThread) {
		useThreadsStore.getState().setLastRunStatus(threadId, status);
		useTriggerRunsStore.getState().setRunStatus(threadId, status);
	}
}

export const useActiveRunsStore = create<ActiveRunsState>((set, get) => ({
	confirmedThreadIds: [],
	optimisticMarkedAt: {},
	pollEpoch: 0,
	lastPolledAt: null,
	pendingSince: null,
	pollSeq: 0,
	markThreadRunning: (threadId) => {
		set((state) => ({
			optimisticMarkedAt: {
				...state.optimisticMarkedAt,
				[threadId]: Date.now(),
			},
			pollEpoch: state.pollEpoch + 1,
		}));
	},
	requestPoll: () => {
		set((state) => ({ pollEpoch: state.pollEpoch + 1 }));
	},
	beginPoll: (now = Date.now()) => {
		const { pollSeq, lastPolledAt, pendingSince } = get();
		const seq = pollSeq + 1;
		set({ pollSeq: seq, pendingSince: pendingSince ?? now });
		return { seq, polledAt: now, ...recentWindow(lastPolledAt ?? pendingSince, now) };
	},
	applyPollResult: (ticket, runs) => {
		if (ticket.seq !== get().pollSeq) return; // a newer poll supersedes this response
		set({ lastPolledAt: ticket.polledAt, pendingSince: null });
		applyFinishedRuns(runs);
		get().setConfirmed(
			runs.filter(isInFlight).map((run) => run.threadId),
			ticket.polledAt,
		);
	},
	setConfirmed: (threadIds, polledAt) => {
		set((state) => {
			const cutoff = Math.min(polledAt - 1_000, Date.now());
			const optimisticMarkedAt = Object.fromEntries(
				Object.entries(state.optimisticMarkedAt).filter(
					([threadId, markedAt]) =>
						!threadIds.includes(threadId) &&
						markedAt > cutoff &&
						Date.now() - markedAt < OPTIMISTIC_RUN_TTL_MS,
				),
			);
			return { confirmedThreadIds: threadIds, optimisticMarkedAt };
		});
	},
}));

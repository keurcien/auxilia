import { create } from "zustand";

/** How long an optimistic mark survives without server confirmation. */
export const OPTIMISTIC_RUN_TTL_MS = 30_000;

interface ActiveRunsState {
	/** Thread ids confirmed in-flight by the last `GET /runs/active` poll. */
	confirmedThreadIds: string[];
	/** Optimistically marked thread ids -> marked-at epoch ms. Shown as
	 * running immediately, until a later poll confirms or supersedes them. */
	optimisticMarkedAt: Record<string, number>;
	/** Bumped by `markThreadRunning` so the poller refreshes immediately. */
	pollEpoch: number;
	/** Show a thread as running right now (run just started client-side). */
	markThreadRunning: (threadId: string) => void;
	/** Record a poll result; prunes optimistic marks older than the poll. */
	setConfirmed: (threadIds: string[], polledAt: number) => void;
}

export const useActiveRunsStore = create<ActiveRunsState>((set) => ({
	confirmedThreadIds: [],
	optimisticMarkedAt: {},
	pollEpoch: 0,
	markThreadRunning: (threadId) => {
		set((state) => ({
			optimisticMarkedAt: {
				...state.optimisticMarkedAt,
				[threadId]: Date.now(),
			},
			pollEpoch: state.pollEpoch + 1,
		}));
	},
	setConfirmed: (threadIds, polledAt) => {
		set((state) => {
			// A poll started after a mark is authoritative for it (the run is
			// registered in Redis before the create call returns); keep a 1s
			// grace for the create/poll race, and a TTL backstop.
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

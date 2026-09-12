import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { Run } from "@/types/runs";
import { useThreadsStore } from "@/stores/threads-store";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";
import {
	MAX_RECENT_S,
	RECENT_MARGIN_S,
	recentWindow,
	useActiveRunsStore,
} from "./active-runs-store";

const run = (threadId: string, status: Run["status"]): Run => ({
	id: `run-${threadId}-${status}`,
	threadId,
	status,
	error: null,
	createdAt: "2026-09-12T00:00:00Z",
	updatedAt: "2026-09-12T00:00:01Z",
});

const initial = useActiveRunsStore.getInitialState();

beforeEach(() => {
	useActiveRunsStore.setState(initial, true);
	vi.useFakeTimers();
	vi.setSystemTime(new Date("2026-09-12T10:00:00Z"));
});

afterEach(() => {
	vi.useRealTimers();
});

describe("recentWindow", () => {
	it("asks only for the margin on the first poll", () => {
		expect(recentWindow(null, Date.now())).toEqual({
			recentSeconds: RECENT_MARGIN_S,
			refetchThreads: false,
		});
	});

	it("covers the gap since the last applied poll, rounded up, plus the margin", () => {
		const now = Date.now();
		expect(recentWindow(now - 4_200, now)).toEqual({
			recentSeconds: 5 + RECENT_MARGIN_S,
			refetchThreads: false,
		});
	});

	it("caps at the backend limit and asks for a full refetch beyond it", () => {
		const now = Date.now();
		expect(recentWindow(now - 2 * 3600 * 1000, now)).toEqual({
			recentSeconds: MAX_RECENT_S,
			refetchThreads: true,
		});
	});
});

describe("poll sequencing", () => {
	it("a superseded poll's response is discarded", () => {
		const store = useActiveRunsStore.getState();
		const older = store.beginPoll();
		const newer = store.beginPoll();
		store.applyPollResult(older, [run("t-old", "running")]);
		expect(useActiveRunsStore.getState().confirmedThreadIds).toEqual([]);
		expect(useActiveRunsStore.getState().lastPolledAt).toBeNull();

		store.applyPollResult(newer, [run("t-new", "running")]);
		expect(useActiveRunsStore.getState().confirmedThreadIds).toEqual(["t-new"]);
		expect(useActiveRunsStore.getState().lastPolledAt).toBe(newer.polledAt);
	});

	it("the next poll's window starts from the last applied poll", () => {
		const store = useActiveRunsStore.getState();
		const first = store.beginPoll();
		store.applyPollResult(first, []);
		vi.advanceTimersByTime(7_000);
		const second = store.beginPoll();
		expect(second.recentSeconds).toBe(7 + RECENT_MARGIN_S);
	});
});

describe("applying a poll", () => {
	it("stamps finished runs into the threads and trigger-runs stores, latest per thread", () => {
		const setLastRunStatus = vi
			.spyOn(useThreadsStore.getState(), "setLastRunStatus")
			.mockImplementation(() => {});
		const setRunStatus = vi
			.spyOn(useTriggerRunsStore.getState(), "setRunStatus")
			.mockImplementation(() => {});
		const store = useActiveRunsStore.getState();
		const ticket = store.beginPoll();
		store.applyPollResult(ticket, [
			run("t1", "error"),
			run("t1", "success"),
			run("t2", "running"),
		]);
		expect(setLastRunStatus).toHaveBeenCalledTimes(1);
		expect(setLastRunStatus).toHaveBeenCalledWith("t1", "success");
		expect(setRunStatus).toHaveBeenCalledWith("t1", "success");
		expect(useActiveRunsStore.getState().confirmedThreadIds).toEqual(["t2"]);
	});

	it("keeps an optimistic mark newer than the poll, drops one the poll should have seen", () => {
		const store = useActiveRunsStore.getState();
		store.markThreadRunning("t-stale");
		vi.advanceTimersByTime(5_000);
		const ticket = store.beginPoll();
		vi.advanceTimersByTime(100);
		store.markThreadRunning("t-fresh"); // marked after the poll went out
		store.applyPollResult(ticket, []);
		expect(Object.keys(useActiveRunsStore.getState().optimisticMarkedAt)).toEqual([
			"t-fresh",
		]);
	});

	it("a confirmed thread no longer needs its optimistic mark", () => {
		const store = useActiveRunsStore.getState();
		store.markThreadRunning("t1");
		const ticket = store.beginPoll();
		store.applyPollResult(ticket, [run("t1", "running")]);
		const state = useActiveRunsStore.getState();
		expect(state.confirmedThreadIds).toEqual(["t1"]);
		expect(state.optimisticMarkedAt).toEqual({});
	});

	it("markThreadRunning and requestPoll both bump the epoch the poller watches", () => {
		const store = useActiveRunsStore.getState();
		store.markThreadRunning("t1");
		store.requestPoll();
		expect(useActiveRunsStore.getState().pollEpoch).toBe(2);
	});
});

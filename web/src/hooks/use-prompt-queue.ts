"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import * as threadsApi from "@/lib/api/resources/threads";
import type { QueuedPrompt } from "@/types/runs";

const POLL_MS = 1000;
/** How long a claimed item counts as "a run is starting" when the stream
 * never reports it (worker crashed before emitting a lifecycle event). */
const CLAIM_GRACE_MS = 5000;

const byPosition = (a: QueuedPrompt, b: QueuedPrompt) =>
	a.position - b.position || a.id.localeCompare(b.id);

export function usePromptQueue(threadId: string, runActive: boolean) {
	const [items, setItems] = useState<QueuedPrompt[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [loadedThreadId, setLoadedThreadId] = useState<string | null>(null);
	// A queued item that vanished from a poll without this client removing
	// it was claimed by the worker: a run is active server-side, even though
	// the stream's `running` lifecycle event hasn't landed yet. The composer
	// must keep queueing through that gap, or a fast Enter starts a direct
	// `submit` that the server parks in the queue anyway — and the prompt
	// shows up both in the conversation and in the queue.
	const [claimedAt, setClaimedAt] = useState<number | null>(null);
	const itemsRef = useRef(items);
	useEffect(() => {
		itemsRef.current = items;
	}, [items]);
	const removedIds = useRef(new Set<string>());
	// Bumped only on thread switch: a response for another thread is dropped.
	const requestVersion = useRef(0);
	const threadIdRef = useRef(threadId);
	// Orders poll responses so an older list can't overwrite a newer one.
	const refreshSeq = useRef(0);
	const refreshInFlight = useRef<{
		threadId: string;
		promise: Promise<void>;
	} | null>(null);
	// Enqueues run one at a time so queue positions follow typing order, and
	// while one is in flight a poll that left before it must not apply its
	// (already stale) list over the optimistic item.
	const enqueueChain = useRef<Promise<void>>(Promise.resolve());
	const enqueueInFlight = useRef(0);

	useEffect(() => {
		threadIdRef.current = threadId;
		requestVersion.current += 1;
		removedIds.current.clear();
		setClaimedAt(null);
	}, [threadId]);

	// The stream confirmed the run (or its end): the claim did its job.
	useEffect(() => {
		if (runActive) setClaimedAt(null);
	}, [runActive]);
	useEffect(() => {
		if (claimedAt == null) return;
		const remaining = claimedAt + CLAIM_GRACE_MS - Date.now();
		const timer = window.setTimeout(
			() => {
				setClaimedAt((current) => (current === claimedAt ? null : current));
			},
			Math.max(0, remaining),
		);
		return () => {
			window.clearTimeout(timer);
		};
	}, [claimedAt]);

	const refresh = useCallback((): Promise<void> => {
		if (refreshInFlight.current?.threadId === threadId) {
			return refreshInFlight.current.promise;
		}
		const version = requestVersion.current;
		const seq = ++refreshSeq.current;
		const promise = threadsApi
			.listQueuedPrompts(threadId)
			.then((next) => {
				if (
					version !== requestVersion.current ||
					threadIdRef.current !== threadId ||
					seq !== refreshSeq.current
				) {
					return;
				}
				if (enqueueInFlight.current === 0) {
					const present = new Set(next.map((item) => item.id));
					const claimed = itemsRef.current.some(
						(item) => !present.has(item.id) && !removedIds.current.has(item.id),
					);
					if (claimed) setClaimedAt(Date.now());
					for (const id of removedIds.current) {
						if (!present.has(id)) removedIds.current.delete(id);
					}
					setItems(next.sort(byPosition));
				}
				setLoadedThreadId(threadId);
			})
			.finally(() => {
				if (refreshInFlight.current?.promise === promise) {
					refreshInFlight.current = null;
				}
				if (
					version === requestVersion.current &&
					threadIdRef.current === threadId
				) {
					setIsLoading(false);
				}
			});
		refreshInFlight.current = { threadId, promise };
		return promise;
	}, [threadId]);

	useEffect(() => {
		void refresh().catch(() => {});
	}, [refresh]);

	// A run starting (a queued item was claimed) or ending (the next one is
	// about to be) is exactly when the list changes: don't wait for the poll.
	useEffect(() => {
		void refresh().catch(() => {});
	}, [refresh, runActive]);

	// A boolean dependency, not `items.length`: resetting the interval on
	// every enqueue meant it never fired while the user was typing fast.
	const shouldPoll =
		runActive || items.length > 0 || loadedThreadId !== threadId;
	useEffect(() => {
		if (!shouldPoll) return;
		const timer = window.setInterval(() => {
			void refresh().catch(() => {});
		}, POLL_MS);
		return () => {
			window.clearInterval(timer);
		};
	}, [refresh, shouldPoll]);

	const enqueue = useCallback(
		(text: string) => {
			const version = requestVersion.current;
			enqueueInFlight.current += 1;
			const operation = enqueueChain.current.then(async () => {
				try {
					const item = await threadsApi.enqueuePrompt(threadId, text);
					if (
						threadIdRef.current !== threadId ||
						version !== requestVersion.current
					) {
						return item;
					}
					setItems((current) =>
						loadedThreadId === threadId
							? [
									...current.filter((candidate) => candidate.id !== item.id),
									item,
								].sort(byPosition)
							: [item],
					);
					setLoadedThreadId(threadId);
					return item;
				} finally {
					enqueueInFlight.current -= 1;
					if (
						enqueueInFlight.current === 0 &&
						threadIdRef.current === threadId
					) {
						// Reconcile with the server once the burst is over (an
						// item may already have been claimed meanwhile).
						void refresh().catch(() => {});
					}
				}
			});
			enqueueChain.current = operation.then(
				() => undefined,
				() => undefined,
			);
			return operation;
		},
		[loadedThreadId, refresh, threadId],
	);

	const update = useCallback(
		async (id: string, text: string) => {
			const version = requestVersion.current;
			try {
				const item = await threadsApi.updateQueuedPrompt(threadId, id, text);
				if (
					threadIdRef.current !== threadId ||
					version !== requestVersion.current
				) {
					return item;
				}
				setItems((current) =>
					current
						.map((candidate) => (candidate.id === id ? item : candidate))
						.sort(byPosition),
				);
				return item;
			} catch (error) {
				if (threadIdRef.current === threadId) {
					void refresh().catch(() => {});
				}
				throw error;
			}
		},
		[refresh, threadId],
	);

	const beginEdit = useCallback(
		async (id: string) => {
			await threadsApi.beginQueuedPromptEdit(threadId, id);
		},
		[threadId],
	);

	const endEdit = useCallback(
		async (id: string) => {
			await threadsApi.endQueuedPromptEdit(threadId, id);
		},
		[threadId],
	);

	const remove = useCallback(
		async (id: string) => {
			const version = requestVersion.current;
			const previous = items;
			removedIds.current.add(id);
			setItems((current) => current.filter((item) => item.id !== id));
			try {
				await threadsApi.removeQueuedPrompt(threadId, id);
			} catch (error) {
				if (
					threadIdRef.current === threadId &&
					version === requestVersion.current
				) {
					removedIds.current.delete(id);
					setItems(previous);
					void refresh().catch(() => {});
				}
				throw error;
			}
		},
		[items, refresh, threadId],
	);

	const reorder = useCallback(
		async (orderedIds: string[]) => {
			const version = requestVersion.current;
			const previous = items;
			const index = new Map(orderedIds.map((id, position) => [id, position]));
			setItems((current) =>
				[...current].sort(
					(a, b) => (index.get(a.id) ?? 0) - (index.get(b.id) ?? 0),
				),
			);
			try {
				const next = await threadsApi.reorderQueuedPrompts(
					threadId,
					orderedIds,
				);
				if (
					threadIdRef.current !== threadId ||
					version !== requestVersion.current
				) {
					return;
				}
				setItems(next.sort(byPosition));
			} catch (error) {
				if (
					threadIdRef.current === threadId &&
					version === requestVersion.current
				) {
					setItems(previous);
					void refresh().catch(() => {});
				}
				throw error;
			}
		},
		[items, refresh, threadId],
	);

	return {
		items: loadedThreadId === threadId ? items : [],
		isLoading: isLoading || loadedThreadId !== threadId,
		/** A queued prompt was just claimed; the stream hasn't confirmed yet. */
		runStarting: claimedAt != null,
		enqueue,
		update,
		beginEdit,
		endEdit,
		remove,
		reorder,
		refresh,
	};
}

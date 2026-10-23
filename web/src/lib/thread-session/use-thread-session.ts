"use client";

import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { isHumanMessage } from "@langchain/core/messages";
import type { BaseMessage } from "@langchain/core/messages";
import { useStream } from "@langchain/react";
import type { AnyStream, SubagentDiscoverySnapshot } from "@langchain/react";
import type { Interrupt } from "@langchain/langgraph-sdk";

import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import type { Todo } from "@/components/ai-elements/todo-list";
import { type HitlDecision, type HitlResponse, useHitlApprovals } from "@/hooks/use-hitl-approvals";
import { useProtocolFetch } from "@/hooks/use-protocol-fetch";
import { useThrottledValue } from "@/hooks/use-throttled-value";
import { protocolApiUrl } from "@/lib/api/protocol";
import * as artifactsApi from "@/lib/api/resources/artifacts";
import * as threadsApi from "@/lib/api/resources/threads";
import {
	extractHitlToolNames,
	getToolStepState,
	pairToolCalls,
	splitInterrupts,
	type ToolCallView,
} from "@/lib/transcript";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useModelsStore } from "@/stores/models-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import type { Run } from "@/types/runs";
import type { ThreadRead } from "@/types/threads";

import { toast } from "sonner";

import { contentPreview, type HumanInput, promptMessageToInput } from "./build-content";
import { EMPTY_HELD, holdInterrupts } from "./interrupt-hold";
import { submitPendingAfterHydration } from "./pending-message";
import {
	initialSessionState,
	lastRunFailed,
	lastRunFallbackMessage,
	pickFailedRunError,
	sessionReducer,
	type SessionMeta,
} from "./session-reducer";

const EMPTY_TODOS: Todo[] = [];

/** Messages that may wait behind a running turn. */
export const QUEUE_LIMIT = 2;

export type QueuedMessage = { id: string; text: string };
type QueuedEntry = { id: string; input: HumanInput };
const EMPTY_QUEUE: QueuedEntry[] = [];
/** Render cadence for the streamed views (tokens arrive far faster). */
const THROTTLE_MS = 60;

/** Everything the session reaches the network through. Tests script it. */
export type ThreadSessionTransport = {
	/** What `useStream` talks to — the protocol endpoints. */
	fetch?: typeof fetch;
	readThread: (threadId: string) => Promise<ThreadRead>;
	listThreadRuns: (threadId: string) => Promise<Run[]>;
	/** Stores an attachment as a thread file; resolves to its id. */
	attachFile: (threadId: string, file: Blob, filename: string) => Promise<string>;
};

export const defaultTransport: ThreadSessionTransport = {
	readThread: threadsApi.readThread,
	listThreadRuns: threadsApi.listThreadRuns,
	attachFile: async (threadId, file, filename) =>
		(await artifactsApi.attachFile(threadId, file, filename)).id,
};

export type ThreadSessionOptions = {
	threadId: string;
	agentId: string;
	transport?: ThreadSessionTransport;
	/** The approval the user addressed was already handled elsewhere. The
	 * page decides what to do (today: reload the page). */
	onStaleInterrupt?: () => void;
	/** A run finished (any outcome). */
	onCompleted?: () => void;
	/** Cap on waiting for hydration before a parked first message is sent. */
	pendingMessageCapMs?: number;
};

export type ThreadSession = {
	meta: SessionMeta;
	/** Why opening failed, when `meta.status === "error"`. */
	openError: unknown;
	run: {
		status: "idle" | "streaming" | "interrupted";
		/** `stream.isLoading` — a run is in flight (also true while a resume is pending). */
		isLoading: boolean;
		/** The stream stack's last error (command rejection or run failure). */
		error: unknown;
		/** Kept separately: the body renders the two differently. */
		rehydratedError: string | null;
	};
	/** Messages sent while a turn runs, held here and sent in order once it
	 * ends; `sendNow` interrupts the turn with one. */
	queue: {
		messages: QueuedMessage[];
		full: boolean;
		sendNow: (id: string) => void;
		remove: (id: string) => void;
	};
	transcript: {
		messages: BaseMessage[];
		toolCalls: ToolCallView[];
		subagents: ReadonlyMap<string, SubagentDiscoverySnapshot>;
		todos: Todo[];
		/** Identity-stable handle for scoped subagent subscriptions. */
		stream: AnyStream;
	};
	hitl: {
		interrupt: Interrupt | null;
		nestedInterrupts: Interrupt[];
		hitlToolNames: Set<string> | null;
		pendingToolCalls: ToolCallView[];
		decisions: Record<string, HitlDecision>;
		recordDecision: (toolCallId: string, decision: HitlDecision) => void;
	};
	actions: {
		/** Queues behind a running turn (see `queue`); a no-op when it is full.
		 * With files, resolves once they are uploaded and rejects if one fails. */
		send: (message: PromptInputMessage) => Promise<void> | undefined;
		regenerate: () => void;
		stop: () => void;
		respond: (response: HitlResponse, interruptId: string | null) => void;
		recheckModel: () => Promise<void>;
		/** Clear the mid-session sandbox gate so the composer comes back; the
		 * page re-polls readiness alongside it. */
		recheckSandbox: () => void;
		/** Run the open sequence again after `meta.status === "error"`. A parked
		 * first message is still parked — it is consumed only once the thread
		 * metadata has loaded. */
		reopen: () => void;
	};
};

/**
 * One thread, as the chat page sees it: what it is doing and what may be done
 * to it. Wraps `useStream` (which owns hydration, reattach and the live
 * projections) with the thread metadata read, the failed-run error
 * rehydration, the HITL batch, the active-run bookkeeping and the parked
 * first message. The ordering rules live in the pure modules next to this
 * file; the page renders the result.
 */
export function useThreadSession({
	threadId,
	agentId,
	transport = defaultTransport,
	onStaleInterrupt,
	onCompleted,
	pendingMessageCapMs,
}: ThreadSessionOptions): ThreadSession {
	const [state, dispatch] = useReducer(sessionReducer, initialSessionState);

	const callbacks = useRef({ onStaleInterrupt, onCompleted });
	useEffect(() => {
		callbacks.current = { onStaleInterrupt, onCompleted };
	});

	const protocolFetch = useProtocolFetch(threadId, {
		baseFetch: transport.fetch,
		onModelUnavailable: (forThread) => {
			dispatch({ type: "model-unavailable", threadId: forThread });
		},
		onSandboxUnavailable: (forThread, detail) => {
			dispatch({ type: "sandbox-unavailable", threadId: forThread, detail });
		},
		onStaleInterrupt: (forThread) => {
			// A late 409 for the thread the page left must not reload this one.
			if (forThread !== threadId) return;
			callbacks.current.onStaleInterrupt?.();
		},
	});

	// The SDK's hydration reads (`getState`, `getHistory`) go through the
	// client's own caller, not `fetch`; hand both the same transport so every
	// protocol request shares the same-origin guard and the session cookie.
	// Memoized: the SDK rebuilds its client (and controller) on identity change.
	const callerOptions = useMemo(() => ({ fetch: protocolFetch }), [protocolFetch]);

	const stream = useStream({
		assistantId: agentId,
		apiUrl: protocolApiUrl(),
		threadId,
		messagesKey: "messages",
		fetch: protocolFetch,
		callerOptions,
		onCompleted: () => {
			useActiveRunsStore.getState().requestPoll();
			callbacks.current.onCompleted?.();
		},
	});

	// `stream` is a new object every tick; the cards subscribe through a
	// handle whose identity never changes.
	const [selectorStream] = useState<AnyStream>(() => stream as AnyStream);
	// …but `hydrationPromise` is replaced by the SDK on every (re)hydrate, so
	// waiting on it must read the latest rendered stream, not the handle.
	const latestStream = useRef(stream);
	latestStream.current = stream;

	// --- interrupts: hold identity while the set is unchanged ----------------
	const [held, setHeld] = useState(EMPTY_HELD);
	const nextHeld = holdInterrupts(held, stream.interrupts);
	if (nextHeld !== held) setHeld(nextHeld);
	const { root: interrupt, nested: nestedInterrupts } = useMemo(
		() => splitInterrupts(held.list),
		[held],
	);
	const isInterrupted = interrupt != null;
	const hitlToolNames = useMemo(
		() => extractHitlToolNames(interrupt?.value),
		[interrupt],
	);

	// --- transcript views -----------------------------------------------------
	const messages = useThrottledValue(stream.messages, THROTTLE_MS);
	const liveToolCalls = useThrottledValue(stream.toolCalls, THROTTLE_MS);
	const toolCalls = useMemo(
		() => pairToolCalls(messages, liveToolCalls),
		[messages, liveToolCalls],
	);
	const todos =
		((stream.values as Record<string, unknown>).todos as Todo[] | undefined) ??
		EMPTY_TODOS;

	// --- actions ----------------------------------------------------------------
	const userActed = useCallback(() => {
		dispatch({ type: "user-acted" });
	}, []);

	// --- the queue ------------------------------------------------------------
	// Ours, not the SDK's `enqueue`: that one queues only behind a run this
	// page started, so after a reload (or a remount) mid-run a message went
	// straight to the server — sent, but no longer queued or sendable now.
	// Busy is `isLoading` (also set for a run reattached on load) or one of
	// our submits not settled yet — `submit()` settles at its run's terminal.
	// The latter covers "send now": the interrupting submit settles the one
	// it replaces, which drops `isLoading` until the new run reports in.
	// Per thread: a submit still settling on the thread left behind must not
	// hold this one's queue.
	const [inFlight, setInFlight] = useState<Record<string, number>>({});
	const busy = stream.isLoading || (inFlight[threadId] ?? 0) > 0;

	const [queueState, setQueueState] = useState<{ threadId: string; items: QueuedEntry[] }>({
		threadId,
		items: [],
	});
	const queueItems = queueState.threadId === threadId ? queueState.items : EMPTY_QUEUE;
	const queueFull = queueItems.length >= QUEUE_LIMIT;
	const queued = useMemo(
		() => queueItems.map((e) => ({ id: e.id, text: contentPreview(e.input) })),
		[queueItems],
	);
	const setQueue = useCallback(
		(update: (items: QueuedEntry[]) => QueuedEntry[]) => {
			setQueueState((q) => ({
				threadId,
				items: update(q.threadId === threadId ? q.items : EMPTY_QUEUE),
			}));
		},
		[threadId],
	);

	const submitContent = useCallback(
		({ content, attachments }: HumanInput, multitaskStrategy: "enqueue" | "interrupt") => {
			userActed();
			const forThread = threadId;
			setInFlight((counts) => ({ ...counts, [forThread]: (counts[forThread] ?? 0) + 1 }));
			const message = attachments.length
				? { type: "human", content, additional_kwargs: { attachments } }
				: { type: "human", content };
			void selectorStream
				.submit({ messages: [message] }, { multitaskStrategy })
				.finally(() => {
					setInFlight((counts) => ({ ...counts, [forThread]: (counts[forThread] ?? 1) - 1 }));
				});
		},
		[selectorStream, threadId, userActed],
	);

	/** False when the queue is full and the message was not taken. */
	const sendInput = useCallback(
		(input: HumanInput): boolean => {
			if (busy || queueItems.length > 0) {
				if (queueFull) return false;
				userActed();
				// Rechecked here: two sends batched in one render both pass `queueFull`.
				setQueue((items) =>
					items.length >= QUEUE_LIMIT ? items : [...items, { id: crypto.randomUUID(), input }],
				);
				return true;
			}
			// `enqueue` server-side too: a run the page cannot see yet still
			// gets waited on rather than rejected.
			submitContent(input, "enqueue");
			return true;
		},
		[busy, queueItems.length, queueFull, setQueue, submitContent, userActed],
	);
	// Read after the uploads settle: the queue state may have moved meanwhile.
	const latestSendInput = useRef(sendInput);
	latestSendInput.current = sendInput;

	// Unknown model (not in the picker list) → assume vision, as the composer does.
	const models = useModelsStore((s) => s.models);
	const modelId = state.meta.thread?.modelId;
	const vision = useRef(true);
	vision.current = models.find((m) => m.id === modelId)?.multimodal !== false;

	// Sends wait on the uploads of the sends before them, so messages keep
	// the order they were written in.
	const currentThread = useRef(threadId);
	currentThread.current = threadId;
	const sendChain = useRef<Promise<unknown>>(Promise.resolve());
	const preparing = useRef(0);

	const send = useCallback(
		(message: PromptInputMessage): Promise<void> | undefined => {
			const files = message.files ?? [];
			// Nothing to upload and nothing ahead: send synchronously.
			if (files.length === 0 && preparing.current === 0) {
				if (message.text?.trim()) sendInput({ content: message.text, attachments: [] });
				return;
			}
			const forThread = threadId;
			const upload = async (file: { url: string; filename?: string }) => {
				// The composer's own data:/blob: URL, never a network destination.
				const blob = await (await fetch(file.url)).blob();
				return transport.attachFile(forThread, blob, file.filename || "file");
			};
			preparing.current += 1;
			const prepared = promptMessageToInput(message, { vision: vision.current, upload });
			const sent = Promise.all([prepared, sendChain.current]).then(([input]) => {
				// The page moved to another thread meanwhile: these files are not its.
				if (input && currentThread.current === forThread && !latestSendInput.current(input))
					throw new Error("Two messages are already waiting. Send this one when the turn ends.");
			});
			sendChain.current = sent.catch(() => undefined);
			// Rejects on a failed upload, so the composer keeps the files to retry.
			return sent
				.catch((error: unknown) => {
					toast.error(error instanceof Error ? error.message : "Could not attach the files.");
					throw error;
				})
				.finally(() => {
					preparing.current -= 1;
				});
		},
		[sendInput, threadId, transport],
	);

	// The turn ended (and is not waiting on an approval, its own or a
	// subagent's): send the next one.
	const awaitingApproval = isInterrupted || nestedInterrupts.length > 0;
	useEffect(() => {
		if (busy || awaitingApproval || queueItems.length === 0) return;
		const [next] = queueItems;
		setQueue((items) => items.filter((e) => e.id !== next.id));
		submitContent(next.input, "enqueue");
	}, [busy, awaitingApproval, queueItems, setQueue, submitContent]);

	const sendNow = useCallback(
		(id: string) => {
			const entry = queueItems.find((e) => e.id === id);
			if (entry == null) return;
			setQueue((items) => items.filter((e) => e.id !== id));
			submitContent(entry.input, "interrupt");
		},
		[queueItems, setQueue, submitContent],
	);

	const removeQueued = useCallback(
		(id: string) => {
			setQueue((items) => items.filter((e) => e.id !== id));
		},
		[setQueue],
	);

	const regenerate = useCallback(() => {
		if (!messages.some(isHumanMessage)) return;
		userActed();
		void selectorStream.submit(null, {
			config: { configurable: { trigger: "regenerate-message" } },
		});
	}, [messages, selectorStream, userActed]);

	const stop = useCallback(() => {
		void selectorStream.stop();
		useActiveRunsStore.getState().requestPoll();
	}, [selectorStream]);

	const respond = useCallback(
		(response: HitlResponse, addressedId: string | null) => {
			userActed();
			void selectorStream.respond(
				response,
				addressedId != null ? { interruptId: addressedId } : undefined,
			);
		},
		[selectorStream, userActed],
	);

	const recheckSandbox = useCallback(() => {
		dispatch({ type: "sandbox-rechecked", threadId });
	}, [threadId]);

	const recheckModel = useCallback(async () => {
		const forThread = threadId;
		try {
			const { thread } = await transport.readThread(forThread);
			dispatch({
				type: "model-rechecked",
				threadId: forThread,
				available: thread.modelAvailable !== false,
			});
		} catch {
			// Leave the banner as it is; the user can try again.
		}
	}, [transport, threadId]);

	// --- HITL batch -------------------------------------------------------------
	const pendingToolCalls = useMemo(
		() =>
			toolCalls.filter(
				(tc) =>
					getToolStepState(tc, isInterrupted, hitlToolNames) === "awaiting-approval",
			),
		[toolCalls, isInterrupted, hitlToolNames],
	);
	const pendingIdsAreReal = pendingToolCalls.every((tc) => tc.callId != null);
	const { decisions, recordDecision } = useHitlApprovals({
		interruptId: pendingIdsAreReal ? (interrupt?.id ?? null) : null,
		pendingToolCalls,
		respond,
	});

	// --- open the thread ------------------------------------------------------
	const consumePendingMessage = usePendingMessageStore((s) => s.consumePendingMessage);
	const setPendingMessage = usePendingMessageStore((s) => s.setPendingMessage);
	const [openAttempt, setOpenAttempt] = useState(0);
	const reopen = useCallback(() => {
		setOpenAttempt((n) => n + 1);
	}, []);
	useEffect(() => {
		// A newer attempt (thread switch or Retry) cancels this one's effects:
		// its responses are dropped rather than landing on the newer state.
		let cancelled = false;
		// The parked message this attempt has taken out of the store and not yet
		// sent. Handed back in the cleanup — synchronously, before a newer
		// attempt's effect body runs — so the newer attempt finds it.
		let claimed: PromptInputMessage | null = null;
		dispatch({ type: "opened", threadId });

		const open = async () => {
			const read = await transport.readThread(threadId);
			if (cancelled) return;
			dispatch({ type: "thread-loaded", threadId, read });

			const pending = consumePendingMessage(threadId);
			if (pending) {
				claimed = pending;
				await submitPendingAfterHydration(
					latestStream.current.hydrationPromise,
					() => {
						// Cancelled while waiting: the cleanup has already parked
						// the message again; sending it here would reach a stream
						// nobody is watching.
						if (cancelled) return;
						claimed = null;
						send(pending);
					},
					{ capMs: pendingMessageCapMs },
				);
				return;
			}

			if (lastRunFailed(read.thread)) {
				const fallback = lastRunFallbackMessage(read.thread);
				const error = await transport
					.listThreadRuns(threadId)
					.then((runs) => pickFailedRunError(runs, fallback))
					.catch(() => fallback);
				if (cancelled) return;
				dispatch({ type: "last-run-error-loaded", threadId, error });
			}
		};
		open().catch((error: unknown) => {
			if (cancelled) return;
			console.error("Could not open the thread:", error);
			dispatch({ type: "open-failed", threadId, error });
		});
		return () => {
			cancelled = true;
			if (claimed) {
				setPendingMessage(threadId, claimed);
				claimed = null;
			}
		};
		// The open sequence runs once per thread (and per explicit reopen); the
		// callbacks it uses are stable.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [threadId, openAttempt]);

	const runStatus: ThreadSession["run"]["status"] = isInterrupted
		? "interrupted"
		: stream.isLoading
			? "streaming"
			: "idle";

	return {
		meta: state.meta,
		openError: state.openError,
		run: {
			status: runStatus,
			isLoading: stream.isLoading,
			error: stream.error,
			rehydratedError: state.rehydratedError,
		},
		queue: { messages: queued, full: queueFull, sendNow, remove: removeQueued },
		transcript: { messages, toolCalls, subagents: stream.subagents, todos, stream: selectorStream },
		hitl: {
			interrupt,
			nestedInterrupts,
			hitlToolNames,
			pendingToolCalls,
			decisions,
			recordDecision,
		},
		actions: { send, regenerate, stop, respond, recheckModel, recheckSandbox, reopen },
	};
}

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
import * as threadsApi from "@/lib/api/resources/threads";
import {
	extractHitlToolNames,
	getToolStepState,
	pairToolCalls,
	splitInterrupts,
	type ToolCallView,
} from "@/lib/transcript";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import type { Run } from "@/types/runs";
import type { ThreadRead } from "@/types/threads";

import { promptMessageToContent } from "./build-content";
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
/** Render cadence for the streamed views (tokens arrive far faster). */
const THROTTLE_MS = 60;

/** Everything the session reaches the network through. Tests script it. */
export type ThreadSessionTransport = {
	/** What `useStream` talks to — the protocol endpoints. */
	fetch?: typeof fetch;
	readThread: (threadId: string) => Promise<ThreadRead>;
	listThreadRuns: (threadId: string) => Promise<Run[]>;
};

export const defaultTransport: ThreadSessionTransport = {
	readThread: threadsApi.readThread,
	listThreadRuns: threadsApi.listThreadRuns,
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
		send: (message: PromptInputMessage) => void;
		regenerate: () => void;
		stop: () => void;
		respond: (response: HitlResponse, interruptId: string | null) => void;
		recheckModel: () => Promise<void>;
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
		onModelUnavailable: () => {
			dispatch({ type: "model-unavailable" });
		},
		onStaleInterrupt: () => {
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

	const send = useCallback(
		(message: PromptInputMessage) => {
			const content = promptMessageToContent(message);
			if (content == null) return;
			userActed();
			void selectorStream.submit({ messages: [{ type: "human", content }] });
		},
		[selectorStream, userActed],
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

	const recheckModel = useCallback(async () => {
		try {
			const { thread } = await transport.readThread(threadId);
			dispatch({ type: "model-rechecked", available: thread.modelAvailable !== false });
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
	const [openAttempt, setOpenAttempt] = useState(0);
	const reopen = useCallback(() => {
		setOpenAttempt((n) => n + 1);
	}, []);
	useEffect(() => {
		dispatch({ type: "opened", threadId });

		const open = async () => {
			const read = await transport.readThread(threadId);
			dispatch({ type: "thread-loaded", threadId, read });

			const pending = consumePendingMessage(threadId);
			if (pending) {
				await submitPendingAfterHydration(
					selectorStream.hydrationPromise,
					() => {
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
				dispatch({ type: "last-run-error-loaded", threadId, error });
			}
		};
		open().catch((error: unknown) => {
			console.error("Could not open the thread:", error);
			dispatch({ type: "open-failed", threadId, error });
		});
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
		transcript: { messages, toolCalls, subagents: stream.subagents, todos, stream: selectorStream },
		hitl: {
			interrupt,
			nestedInterrupts,
			hitlToolNames,
			pendingToolCalls,
			decisions,
			recordDecision,
		},
		actions: { send, regenerate, stop, respond, recheckModel, reopen },
	};
}

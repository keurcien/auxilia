import type { Run } from "@/types/runs";
import type { Thread, ThreadRead, ViewerRole } from "@/types/threads";

/**
 * The page-local half of a thread session — everything about the thread that
 * is *not* the stream: metadata, viewer role, model availability and the
 * error of a run that failed before this page opened.
 *
 * Pure. The ordering rule that used to live in a ref (`rehydratedErrorStale`)
 * is `userActed`: once the user sends, responds or regenerates, a failed-run
 * error that arrives afterwards belongs to a run they have already moved past.
 */
export type SessionMeta = {
	status: "loading" | "ready" | "error";
	thread: Thread | null;
	viewerRole: ViewerRole | null;
	/** False once a workspace admin disabled the thread's pinned model. */
	modelAvailable: boolean;
	agentArchived: boolean;
};

export type SessionState = {
	/** The thread this state belongs to; events for another thread are ignored. */
	threadId: string | null;
	meta: SessionMeta;
	/** Why opening failed (`meta.status === "error"`), for the retry banner. */
	openError: unknown;
	/** Error text of the last failed run, shown until the user acts. */
	rehydratedError: string | null;
	userActed: boolean;
};

export type SessionEvent =
	/** A thread is being opened: every session-scoped field starts over. */
	| { type: "opened"; threadId: string }
	| { type: "thread-loaded"; threadId: string; read: ThreadRead }
	| { type: "open-failed"; threadId: string; error: unknown }
	| { type: "last-run-error-loaded"; threadId: string; error: string }
	| { type: "user-acted" }
	| { type: "model-unavailable"; threadId: string }
	| { type: "model-rechecked"; threadId: string; available: boolean };

export const initialSessionState: SessionState = {
	threadId: null,
	meta: {
		status: "loading",
		thread: null,
		viewerRole: null,
		modelAvailable: true,
		agentArchived: false,
	},
	openError: null,
	rehydratedError: null,
	userActed: false,
};

export function sessionReducer(
	state: SessionState,
	event: SessionEvent,
): SessionState {
	// Loads race thread switches: a response for the thread the page left
	// must not land on the thread it moved to.
	if ("threadId" in event && event.type !== "opened" && event.threadId !== state.threadId) {
		return state;
	}
	switch (event.type) {
		case "opened":
			return { ...initialSessionState, threadId: event.threadId };
		case "thread-loaded": {
			const { thread, viewerRole } = event.read;
			return {
				...state,
				openError: null,
				meta: {
					status: "ready",
					thread,
					viewerRole: viewerRole === "admin" ? "admin" : null,
					modelAvailable: thread.modelAvailable !== false,
					agentArchived: thread.agentArchived,
				},
			};
		}
		case "open-failed":
			return { ...state, openError: event.error, meta: { ...state.meta, status: "error" } };
		case "last-run-error-loaded":
			// A slow fetch must not resurrect the previous run's error.
			return state.userActed ? state : { ...state, rehydratedError: event.error };
		case "user-acted":
			return state.userActed && state.rehydratedError === null
				? state
				: { ...state, userActed: true, rehydratedError: null };
		case "model-unavailable":
			return state.meta.modelAvailable
				? { ...state, meta: { ...state.meta, modelAvailable: false } }
				: state;
		case "model-rechecked":
			return state.meta.modelAvailable === event.available
				? state
				: { ...state, meta: { ...state.meta, modelAvailable: event.available } };
	}
}

/** Whether the thread's last run ended in a way the composer should surface. */
export function lastRunFailed(thread: Thread): boolean {
	return thread.lastRunStatus === "error" || thread.lastRunStatus === "timeout";
}

/** Generic text for a failed run, when the run record carries none. */
export function lastRunFallbackMessage(thread: Thread): string {
	return thread.lastRunStatus === "timeout"
		? "The last run exceeded the time limit."
		: "The last run failed.";
}

/** The error of the run that stamped `lastRunStatus` — newest first, so the
 * first failed run. Falls back to the generic text. */
export function pickFailedRunError(runs: readonly Run[], fallback: string): string {
	const failed = runs.find((r) => r.status === "error" || r.status === "timeout");
	return failed?.error || fallback;
}

/** What the chat header shows for this thread. */
export type ChatHeaderData = {
	agentName: string | null;
	agentEmoji: string | null;
	agentColor: string | null;
	modelId: string | null;
	triggerId: string | null;
	triggerName: string | null;
	triggerRunAt: string | null;
};

export function chatHeaderFromThread(thread: Thread): ChatHeaderData {
	const isTrigger = thread.source === "trigger";
	return {
		agentName: thread.agentName ?? null,
		agentEmoji: thread.agentEmoji ?? null,
		agentColor: thread.agentColor ?? null,
		modelId: thread.modelId ?? null,
		triggerId: isTrigger ? (thread.triggerId ?? null) : null,
		triggerName: isTrigger ? (thread.firstMessageContent ?? null) : null,
		triggerRunAt: isTrigger ? (thread.createdAt ?? null) : null,
	};
}

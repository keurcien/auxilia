import { RunTerminalStatus } from "@/types/runs";

export type ThreadSource = "web" | "slack" | "api" | "trigger";

export interface Thread {
	id: string;
	agentId: string;
	userId: string;
	/** The thread's title; null for threads created without one (Slack, API). */
	firstMessageContent: string | null;
	agentName: string | null;
	agentEmoji: string | null;
	agentColor: string | null;
	agentArchived: boolean;
	source: ThreadSource;
	triggerId?: string | null;
	/** Outcome of the most recent run; null = no finished run. In-flight state
	 * comes from the active-runs poll, never from this field. */
	lastRunStatus?: RunTerminalStatus | null;
	createdAt: string;
	/** Pinned at creation, never patched. Present on a full thread read;
	 * optional because sidebar rows built client-side (a trigger firing) omit them. */
	modelId?: string | null;
	reasoningEffort?: string | null;
	/** False once a workspace admin disabled the pinned model. */
	modelAvailable?: boolean;
	updatedAt?: string;
}

/** Roles a non-owner may hold on a thread — today only a workspace admin, read-only. */
export type ViewerRole = "admin";

/** `GET /threads/{id}`: metadata plus the caller's role. The conversation is
 * not here — the client hydrates it from the protocol snapshot. */
export interface ThreadRead {
	thread: Thread;
	viewerRole: ViewerRole | null;
}

/** `POST /threads` payload. The id is client-generated so the composer can
 * park the first message under it before navigating. */
export interface ThreadCreate {
	id?: string;
	agentId: string;
	/** Omit (or null) to let the server pick the workspace default model. */
	modelId?: string | null;
	reasoningEffort: string | null;
	firstMessageContent?: string;
}

export interface AgentThread extends Thread {
	userEmail: string | null;
	userName: string | null;
}

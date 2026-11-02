import { RunTerminalStatus } from "@/types/runs";

export type ThreadSource =
	| "web"
	| "slack"
	| "telegram"
	| "whatsapp"
	| "api"
	| "trigger";
export type ThreadToolMode =
	| "no_tools"
	| "eager"
	| "lazy"
	| "precision"
	| "force_all";

export interface Thread {
	id: string;
	agentId: string;
	userId: string;
	/** The thread's title; null for threads created without one (Slack, API). */
	firstMessageContent: string | null;
	agentName: string | null;
	agentEmoji: string | null;
	agentColor: string | null;
	agentImageRevision?: string | null;
	agentArchived: boolean;
	source: ThreadSource;
	triggerId?: string | null;
	projectId?: string | null;
	folderId?: string | null;
	completedAt?: string | null;
	/** Outcome of the most recent run; null = no finished run. In-flight state
	 * comes from the active-runs poll, never from this field. */
	lastRunStatus?: RunTerminalStatus | null;
	createdAt: string;
	/** Present on a full thread read; optional because sidebar rows built
	 * client-side (a trigger firing) omit model settings. */
	modelId?: string | null;
	reasoningEffort?: string | null;
	/** Null inherits the agent's configured discovery mode. */
	toolMode?: ThreadToolMode | null;
	/** Whether personal memories may be read or updated in this conversation. */
	memoriesEnabled?: boolean;
	/** False once the thread's current model is no longer available. */
	modelAvailable?: boolean;
	disabledMcpServerIds?: string[];
	disabledSkillIds?: string[];
	disabledSandboxIds?: string[];
	disabledSubagentIds?: string[];
	updatedAt?: string;
}

/** Read-only roles a non-owner may hold on a thread. */
export type ViewerRole = "admin" | "viewer";

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
	/** The starter page resolves the agent/workspace default before calling so
	 * the selected value is explicit in the newly created conversation. */
	modelId: string;
	reasoningEffort: string | null;
	/** Omitted/null inherits the agent's configured discovery mode. */
	toolMode?: ThreadToolMode | null;
	memoriesEnabled?: boolean;
	firstMessageContent?: string;
	projectId?: string | null;
	folderId?: string | null;
	disabledMcpServerIds?: string[];
	disabledSkillIds?: string[];
	disabledSandboxIds?: string[];
	disabledSubagentIds?: string[];
}

export interface ThreadResourceSettings {
	toolMode: ThreadToolMode | null;
	disabledMcpServerIds: string[];
	disabledSkillIds: string[];
	disabledSandboxIds: string[];
	disabledSubagentIds: string[];
}

export interface AgentThread extends Thread {
	userEmail: string | null;
	userName: string | null;
}

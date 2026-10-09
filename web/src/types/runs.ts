export type RunStatus =
	| "pending"
	| "running"
	| "interrupted"
	| "success"
	| "error"
	| "timeout"
	| "cancelled";

/** Statuses a finished run can settle on — what `lastRunStatus` fields carry. */
export type RunTerminalStatus = Exclude<RunStatus, "pending" | "running">;

/** API projection of a run (`RunResponse`) — operational state only. */
export interface Run {
	id: string;
	/** Present on backend RunResponse; optional for locally synthesized run state. */
	workspaceId?: string;
	threadId: string;
	status: RunStatus;
	error: string | null;
	createdAt: string;
	updatedAt: string;
}

/** What `GET /runs/active` returns: in-flight runs plus recently finished ones. */
export type ActiveRun = Run;

/** A text-only run waiting behind the current turn. */
export interface QueuedPrompt {
	id: string;
	text: string;
	position: number;
	createdAt: string;
	updatedAt: string;
}

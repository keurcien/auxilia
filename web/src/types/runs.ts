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
	threadId: string;
	status: RunStatus;
	error: string | null;
	createdAt: string;
	updatedAt: string;
}

/** What `GET /runs/active` returns: in-flight runs plus recently finished ones. */
export type ActiveRun = Run;

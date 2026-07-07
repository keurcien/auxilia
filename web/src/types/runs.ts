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

export interface ActiveRun {
	id: string;
	threadId: string;
	status: RunStatus;
	error: string | null;
	createdAt: string;
	updatedAt: string;
}

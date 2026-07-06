export type RunStatus =
	| "pending"
	| "running"
	| "interrupted"
	| "success"
	| "error"
	| "timeout"
	| "cancelled";

export interface ActiveRun {
	id: string;
	threadId: string;
	status: RunStatus;
	error: string | null;
	createdAt: string;
	updatedAt: string;
}

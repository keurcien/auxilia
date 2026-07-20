import { RunTerminalStatus } from "@/types/runs";

export interface Trigger {
	id: string;
	name: string;
	instructions: string;
	ownerId: string;
	agentId: string;
	modelId: string;
	cronExpression: string;
	timezone: string;
	isActive: boolean;
	nextRunAt: string | null;
	lastRunAt: string | null;
	createdAt: string;
	updatedAt: string;
	/** Server-computed: the trigger's model is usable right now. When false,
	 * scheduled firings are being skipped and Run now would be rejected. */
	modelAvailable: boolean;
	/** Whitelist display name for modelId, set even when the model is
	 * unavailable. Null = the model left the whitelist; fall back to modelId. */
	modelDisplayName: string | null;
}

export interface TriggerCreate {
	name: string;
	instructions: string;
	agentId: string;
	modelId: string;
	cronExpression: string;
	timezone: string;
	isActive?: boolean;
}

export interface TriggerUpdate {
	name?: string;
	instructions?: string;
	agentId?: string;
	modelId?: string;
	cronExpression?: string;
	timezone?: string;
	isActive?: boolean;
}

export interface TriggerRun {
	threadId: string;
	runId: string;
}

export interface SchedulePreview {
	nextRunAts: string[];
}

export interface TriggerThread {
	id: string;
	agentId: string;
	firstMessageContent: string | null;
	/** Outcome of the firing's run; null while in flight. */
	lastRunStatus?: RunTerminalStatus | null;
	createdAt: string;
}

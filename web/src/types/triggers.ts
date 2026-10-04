import { RunTerminalStatus } from "@/types/runs";

export type TriggerType = "schedule" | "webhook";

interface TriggerBase {
	id: string;
	name: string;
	instructions: string;
	ownerId: string;
	agentId: string;
	modelId: string;
	reasoningEffort: string | null;
	triggerType: TriggerType;
	isActive: boolean;
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

export interface ScheduleTrigger extends TriggerBase {
	triggerType: "schedule";
	cronExpression: string;
	timezone: string;
	webhookUrl: null;
	nextRunAt: string | null;
}

export interface WebhookTrigger extends TriggerBase {
	triggerType: "webhook";
	cronExpression: null;
	timezone: null;
	webhookUrl: string;
	nextRunAt: null;
}

export type Trigger = ScheduleTrigger | WebhookTrigger;

interface TriggerCreateBase {
	name: string;
	instructions: string;
	agentId: string;
	modelId: string;
	isActive?: boolean;
}

export interface ScheduleTriggerCreate extends TriggerCreateBase {
	triggerType?: "schedule";
	cronExpression: string;
	timezone: string;
}

export interface WebhookTriggerCreate extends TriggerCreateBase {
	triggerType: "webhook";
}

export type TriggerCreate = ScheduleTriggerCreate | WebhookTriggerCreate;

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

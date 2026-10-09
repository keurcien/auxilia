import { RunTerminalStatus } from "@/types/runs";
import type { ResourceVisibility } from "@/types/visibility";

export type TriggerType = "schedule" | "webhook";

interface TriggerBase {
	id: string;
	name: string;
	group: string | null;
	instructions: string;
	ownerId: string;
	visibility: ResourceVisibility;
	teamIds: string[];
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
	canManage: boolean;
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
	webhookUrl: string | null;
	nextRunAt: null;
}

export type Trigger = ScheduleTrigger | WebhookTrigger;

interface TriggerCreateBase {
	name: string;
	group?: string | null;
	instructions: string;
	agentId: string;
	modelId: string;
	reasoningEffort?: string | null;
	isActive?: boolean;
	visibility?: ResourceVisibility;
	teamIds?: string[];
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
	group?: string | null;
	instructions?: string;
	agentId?: string;
	modelId?: string;
	cronExpression?: string;
	timezone?: string;
	isActive?: boolean;
	visibility?: ResourceVisibility;
	teamIds?: string[];
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

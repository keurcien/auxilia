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
	effectiveVisibility: ResourceVisibility;
	effectiveTeamIds: string[];
	projectId: string | null;
	folderId: string | null;
	agentId: string;
	/** Null follows the agent's default model, else the workspace default. */
	modelId: string | null;
	reasoningEffort: string | null;
	triggerType: TriggerType;
	isActive: boolean;
	notificationsEnabled: boolean;
	/** One-shot: the first scheduled or webhook firing pauses the trigger. */
	runOnce: boolean;
	/** Each firing's conversation is marked completed once its run succeeds. */
	autoComplete: boolean;
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
	disabledMcpServerIds: string[] | null;
	disabledSkillIds: string[] | null;
	disabledSandboxIds: string[] | null;
	disabledSubagentIds: string[] | null;
	disabledMcpTools: Record<string, string[]> | null;
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
	modelId?: string | null;
	reasoningEffort?: string | null;
	isActive?: boolean;
	notificationsEnabled?: boolean;
	runOnce?: boolean;
	autoComplete?: boolean;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	projectId?: string | null;
	folderId?: string | null;
	disabledMcpServerIds?: string[] | null;
	disabledSkillIds?: string[] | null;
	disabledSandboxIds?: string[] | null;
	disabledSubagentIds?: string[] | null;
	disabledMcpTools?: Record<string, string[]> | null;
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
	/** null = follow the agent or workspace default. */
	modelId?: string | null;
	/** null = the model's default. */
	reasoningEffort?: string | null;
	cronExpression?: string;
	timezone?: string;
	isActive?: boolean;
	notificationsEnabled?: boolean;
	runOnce?: boolean;
	autoComplete?: boolean;
	visibility?: ResourceVisibility;
	teamIds?: string[];
	projectId?: string | null;
	folderId?: string | null;
	disabledMcpServerIds?: string[] | null;
	disabledSkillIds?: string[] | null;
	disabledSandboxIds?: string[] | null;
	disabledSubagentIds?: string[] | null;
	disabledMcpTools?: Record<string, string[]> | null;
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

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
	createdAt: string;
}

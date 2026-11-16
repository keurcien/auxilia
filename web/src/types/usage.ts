/** What usage numbers cover: the caller's own, a workspace, or every workspace. */
export type UsageScope = "personal" | "workspace" | "instance";

export type UsageGranularity = "day" | "week" | "month";

export type UsageDimension =
	| "channel"
	| "agent"
	| "project"
	| "trigger"
	| "user"
	| "model"
	| "vendor"
	| "workspace";

export type UsageChannel =
	| "web"
	| "api"
	| "slack"
	| "telegram"
	| "whatsapp"
	| "schedule"
	| "webhook"
	| "trigger";

export interface UsageTokens {
	input: number;
	cacheRead: number;
	cacheCreation: number;
	output: number;
	total: number;
}

/** Amounts are in the workspace display currency. */
export interface UsageTotals {
	cost: number;
	calls: number;
	unpricedCalls: number;
	tokens: UsageTokens;
}

export interface UsageCurrency {
	code: string;
	usdRate: number;
}

export interface UsageSummary {
	month: UsageTotals;
	previousMonth: UsageTotals;
	year: UsageTotals;
	allTime: UsageTotals;
}

/** One model or vendor's share of an entity's usage. */
export interface UsageSplit {
	/** Model id or vendor slug; null for models outside the catalog. */
	key: string | null;
	label: string;
	/** Vendor slug, for its logo. */
	vendor: string | null;
	summary: UsageSummary;
}

export interface UsageSummaryResponse extends UsageSummary {
	scope: UsageScope;
	currency: UsageCurrency;
	/** Ranked by all-time cost. */
	vendors: UsageSplit[];
	models: UsageSplit[];
}

export interface UsageSummariesResponse {
	scope: UsageScope;
	currency: UsageCurrency;
	dimension: UsageDimension;
	items: Record<string, UsageSummary>;
}

export interface UsageSeriesPoint {
	start: string;
	cost: number;
	tokens: number;
	calls: number;
	costByChannel: Partial<Record<UsageChannel, number>>;
}

export interface UsageBreakdownRow {
	key: string | null;
	label: string;
	cost: number;
	previousCost: number;
	calls: number;
	unpricedCalls: number;
	tokens: number;
	share: number;
	/** Vendor slug of model and vendor rows, for their logo. */
	vendor?: string | null;
}

export interface UsageBudget {
	monthly: number;
	monthToDate: number;
	projected: number;
}

export interface UsageReport {
	scope: UsageScope;
	currency: UsageCurrency;
	start: string;
	end: string;
	previousStart: string;
	previousEnd: string;
	granularity: UsageGranularity;
	totals: UsageTotals;
	previousTotals: UsageTotals;
	series: UsageSeriesPoint[];
	breakdowns: Partial<Record<UsageDimension, UsageBreakdownRow[]>>;
	budget: UsageBudget | null;
	trackingStartedAt: string | null;
	backfillCompleted: boolean;
}

export interface UsageReportParams {
	start?: string;
	end?: string;
	granularity: UsageGranularity;
	scope?: UsageScope;
	agentId?: string;
	projectId?: string;
	triggerId?: string;
	userId?: string;
	channel?: UsageChannel;
}

export interface UsageSummaryParams {
	scope?: UsageScope;
	agentId?: string;
	projectId?: string;
	triggerId?: string;
	userId?: string;
}

export interface UsageSettings {
	currency: string;
	usdRate: number;
	monthlyBudget: number | null;
	supportedCurrencies: string[];
}

export interface UsageSettingsUpdate {
	currency: string;
	usdRate: number;
	monthlyBudget: number | null;
}

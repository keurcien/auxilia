import { api } from "@/lib/api/client";
import { browserTimeZone } from "@/lib/usage/format";
import type {
	UsageDimension,
	UsageReport,
	UsageReportParams,
	UsageScope,
	UsageSettings,
	UsageSettingsUpdate,
	UsageSummariesResponse,
	UsageSummaryParams,
	UsageSummaryResponse,
} from "@/types/usage";

export async function getUsageReport(
	params: UsageReportParams,
): Promise<UsageReport> {
	const response = await api.get<UsageReport>("/usage/report", {
		params: { ...params, tz: browserTimeZone() },
	});
	return response.data;
}

export async function getUsageSummary(
	params: UsageSummaryParams,
): Promise<UsageSummaryResponse> {
	const response = await api.get<UsageSummaryResponse>("/usage/summary", {
		params: { ...params, tz: browserTimeZone() },
	});
	return response.data;
}

export async function getUsageSummaries(
	dimension: UsageDimension,
	scope?: UsageScope,
): Promise<UsageSummariesResponse> {
	const response = await api.get<UsageSummariesResponse>("/usage/summaries", {
		params: { dimension, scope, tz: browserTimeZone() },
	});
	return response.data;
}

export async function getUsageSettings(): Promise<UsageSettings> {
	return (await api.get<UsageSettings>("/usage/settings")).data;
}

export async function updateUsageSettings(
	update: UsageSettingsUpdate,
): Promise<UsageSettings> {
	return (await api.put<UsageSettings>("/usage/settings", update)).data;
}

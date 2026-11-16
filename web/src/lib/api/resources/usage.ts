import { api } from "@/lib/api/client";
import { browserTimeZone } from "@/lib/usage/format";
import type {
	UsageDimension,
	UsageFilterOption,
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

export async function searchUsageFilterOptions(
	query: string,
	scope: UsageScope | undefined,
	signal: AbortSignal,
): Promise<UsageFilterOption[]> {
	const response = await api.get<{ options: UsageFilterOption[] }>(
		"/usage/filter-options",
		{ params: { q: query, scope }, signal },
	);
	return response.data.options;
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

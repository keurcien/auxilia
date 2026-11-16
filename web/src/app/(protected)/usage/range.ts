import { isoDate } from "@/lib/usage/format";
import type { UsageGranularity } from "@/types/usage";

export type RangePreset =
	| "7d"
	| "30d"
	| "90d"
	| "month"
	| "last-month"
	| "year"
	| "all";

export const RANGE_PRESETS: { key: RangePreset; label: string }[] = [
	{ key: "7d", label: "Last 7 days" },
	{ key: "30d", label: "Last 30 days" },
	{ key: "90d", label: "Last 90 days" },
	{ key: "month", label: "This month" },
	{ key: "last-month", label: "Last month" },
	{ key: "year", label: "This year" },
	{ key: "all", label: "All time" },
];

export const DEFAULT_PRESET: RangePreset = "30d";

export function parsePreset(value: string): RangePreset {
	return RANGE_PRESETS.some((preset) => preset.key === value)
		? (value as RangePreset)
		: DEFAULT_PRESET;
}

/** Inclusive local dates; `all` leaves the start to the server (first call). */
export function presetDates(
	preset: RangePreset,
	today = new Date(),
): { start?: string; end?: string } {
	const daysAgo = (days: number) => {
		const date = new Date(today);
		date.setDate(date.getDate() - days);
		return isoDate(date);
	};
	const year = today.getFullYear();
	const month = today.getMonth();
	switch (preset) {
		case "7d":
			return { start: daysAgo(6), end: isoDate(today) };
		case "30d":
			return { start: daysAgo(29), end: isoDate(today) };
		case "90d":
			return { start: daysAgo(89), end: isoDate(today) };
		case "month":
			return { start: isoDate(new Date(year, month, 1)), end: isoDate(today) };
		case "last-month":
			return {
				start: isoDate(new Date(year, month - 1, 1)),
				end: isoDate(new Date(year, month, 0)),
			};
		case "year":
			return { start: isoDate(new Date(year, 0, 1)), end: isoDate(today) };
		case "all":
			return { end: isoDate(today) };
	}
}

/** Granularities that give a readable chart for a preset; the first is the default. */
export function presetGranularities(preset: RangePreset): UsageGranularity[] {
	switch (preset) {
		case "7d":
		case "30d":
		case "month":
		case "last-month":
			return ["day", "week"];
		case "90d":
			return ["week", "day", "month"];
		case "year":
			return ["week", "month", "day"];
		case "all":
			return ["month", "week"];
	}
}

export const GRANULARITY_LABELS: Record<UsageGranularity, string> = {
	day: "Daily",
	week: "Weekly",
	month: "Monthly",
};

/** Days in an inclusive `YYYY-MM-DD` range. */
export function rangeDays(start: string, end: string): number {
	const [from, to] = [start, end].map((value) => Date.parse(`${value}T00:00:00Z`));
	return Math.round((to - from) / 86_400_000) + 1;
}

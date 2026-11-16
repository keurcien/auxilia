import { formatRange, isoDate } from "@/lib/usage/format";
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

/** A preset, or an inclusive custom range of local dates. */
export type UsageRange =
	| { preset: RangePreset }
	| { preset: "custom"; start: string; end: string };

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const CUSTOM_SEPARATOR = "..";

/** The `range` query param: a preset key, or `YYYY-MM-DD..YYYY-MM-DD`. */
export function parseRange(value: string): UsageRange {
	const preset = RANGE_PRESETS.find((option) => option.key === value);
	if (preset) return { preset: preset.key };
	const [start, end, ...rest] = value.split(CUSTOM_SEPARATOR);
	if (
		rest.length === 0 &&
		ISO_DATE.test(start ?? "") &&
		ISO_DATE.test(end ?? "") &&
		!Number.isNaN(Date.parse(start)) &&
		!Number.isNaN(Date.parse(end)) &&
		start <= end
	) {
		return { preset: "custom", start, end };
	}
	return { preset: DEFAULT_PRESET };
}

export function serializeRange(range: UsageRange): string {
	if (range.preset === "custom") return `${range.start}${CUSTOM_SEPARATOR}${range.end}`;
	return range.preset === DEFAULT_PRESET ? "" : range.preset;
}

export function rangeLabel(range: UsageRange): string {
	if (range.preset === "custom") return formatRange(range.start, range.end);
	return RANGE_PRESETS.find((option) => option.key === range.preset)?.label ?? "";
}

/** Inclusive local dates; `all` leaves the start to the server (first call). */
export function rangeDates(
	range: UsageRange,
	today = new Date(),
): { start?: string; end?: string } {
	const daysAgo = (days: number) => {
		const date = new Date(today);
		date.setDate(date.getDate() - days);
		return isoDate(date);
	};
	const year = today.getFullYear();
	const month = today.getMonth();
	switch (range.preset) {
		case "custom":
			return { start: range.start, end: range.end };
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

/** The server caps a series at 800 points. */
const MAX_DAILY_POINTS = 800;

/** Granularities that give a readable chart for a range; the first is the default. */
export function rangeGranularities(range: UsageRange): UsageGranularity[] {
	switch (range.preset) {
		case "custom": {
			const days = rangeDays(range.start, range.end);
			if (days <= 45) return ["day", "week"];
			if (days <= 180) return ["week", "day", "month"];
			if (days <= MAX_DAILY_POINTS) return ["week", "month", "day"];
			return ["month", "week"];
		}
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

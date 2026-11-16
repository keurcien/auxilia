import type {
	UsageChannel,
	UsageGranularity,
	UsageTotals,
} from "@/types/usage";

export function browserTimeZone(): string {
	return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** Money in the display currency: "< €0.01" for dust, compact above 10k. */
export function formatMoney(
	amount: number,
	currency: string,
	options: { precise?: boolean } = {},
): string {
	if (amount > 0 && amount < 0.01 && !options.precise) {
		return `< ${formatMoney(0.01, currency)}`;
	}
	const compact = !options.precise && Math.abs(amount) >= 10_000;
	return new Intl.NumberFormat(undefined, {
		style: "currency",
		currency,
		notation: compact ? "compact" : "standard",
		minimumFractionDigits: compact ? 0 : 2,
		maximumFractionDigits: options.precise ? 6 : compact ? 1 : 2,
	}).format(amount);
}

/** Token counts: "840", "12.4K", "3.1M". */
export function formatTokens(count: number): string {
	return new Intl.NumberFormat(undefined, {
		notation: count >= 10_000 ? "compact" : "standard",
		maximumFractionDigits: 1,
	}).format(count);
}

export function formatCount(count: number): string {
	return new Intl.NumberFormat().format(count);
}

/** Relative change, or null when there is nothing to compare with. */
export function relativeChange(current: number, previous: number): number | null {
	if (previous <= 0) return null;
	return (current - previous) / previous;
}

export function formatChange(change: number): string {
	const percent = Math.round(change * 100);
	return `${percent > 0 ? "+" : ""}${percent}%`;
}

/** A total that leaves unpriced calls out reads as a lower bound. */
export function isPartial(totals: UsageTotals): boolean {
	return totals.unpricedCalls > 0 && totals.unpricedCalls < totals.calls;
}

export const CHANNEL_META: Record<UsageChannel, { label: string; color: string }> = {
	web: { label: "Web chat", color: "#16606E" },
	schedule: { label: "Scheduled triggers", color: "#3D8B63" },
	webhook: { label: "Webhook triggers", color: "#7B6CC4" },
	slack: { label: "Slack", color: "#C27A3A" },
	api: { label: "API", color: "#5B8DB8" },
	telegram: { label: "Telegram", color: "#45A6C9" },
	whatsapp: { label: "WhatsApp", color: "#B5A23A" },
	trigger: { label: "Deleted triggers", color: "#A3ADA8" },
};

export const CHANNEL_ORDER: UsageChannel[] = [
	"web",
	"schedule",
	"webhook",
	"slack",
	"api",
	"telegram",
	"whatsapp",
	"trigger",
];

/** `YYYY-MM-DD` of a local date. */
export function isoDate(date: Date): string {
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return `${date.getFullYear()}-${month}-${day}`;
}

/** Parse a `YYYY-MM-DD` as a local calendar date. */
export function parseIsoDate(value: string): Date {
	const [year, month, day] = value.split("-").map(Number);
	return new Date(year, month - 1, day);
}

export function formatBucket(
	start: string,
	granularity: UsageGranularity,
	style: "short" | "long" = "short",
): string {
	const date = parseIsoDate(start);
	if (granularity === "month") {
		return date.toLocaleDateString(undefined, {
			month: style === "long" ? "long" : "short",
			year: style === "long" ? "numeric" : "2-digit",
		});
	}
	const label = date.toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
		...(style === "long" ? { year: "numeric" } : {}),
	});
	return granularity === "week" && style === "long" ? `Week of ${label}` : label;
}

export function formatRange(start: string, end: string): string {
	const from = parseIsoDate(start);
	const to = parseIsoDate(end);
	const sameYear = from.getFullYear() === to.getFullYear();
	const left = from.toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
		...(sameYear ? {} : { year: "numeric" }),
	});
	const right = to.toLocaleDateString(undefined, {
		month: "short",
		day: "numeric",
		year: "numeric",
	});
	return start === end ? right : `${left} to ${right}`;
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, Coins, TrendingDown, TrendingUp } from "lucide-react";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import {
	HoverCard,
	HoverCardContent,
	HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
	formatChange,
	formatCount,
	formatMoney,
	formatTokens,
	isPartial,
	relativeChange,
} from "@/lib/usage/format";
import { cn } from "@/lib/utils";
import {
	detailKey,
	type UsageEntityDimension,
	useUsageSummariesStore,
} from "@/stores/usage-summaries-store";
import type {
	UsageDimension,
	UsageScope,
	UsageSplit,
	UsageSummary,
	UsageSummaryResponse,
	UsageTotals,
} from "@/types/usage";

const EMPTY_TOTALS: UsageTotals = {
	cost: 0,
	calls: 0,
	unpricedCalls: 0,
	tokens: { input: 0, cacheRead: 0, cacheCreation: 0, output: 0, total: 0 },
};

const EMPTY_SUMMARY: UsageSummary = {
	month: EMPTY_TOTALS,
	previousMonth: EMPTY_TOTALS,
	year: EMPTY_TOTALS,
	allTime: EMPTY_TOTALS,
};

const TOKEN_SEGMENTS = [
	{ key: "input", label: "Input", className: "bg-petrol" },
	{ key: "cacheRead", label: "Cached", className: "bg-petrol/45" },
	{ key: "cacheCreation", label: "Cache write", className: "bg-[#C27A3A]" },
	{ key: "output", label: "Output", className: "bg-[#3D8B63]" },
] as const;

const DIMENSION_PARAM: Partial<Record<UsageDimension, string>> = {
	agent: "agent",
	project: "project",
	trigger: "trigger",
	user: "user",
};

export function usageHref(dimension: UsageDimension, id: string): string {
	const param = DIMENSION_PARAM[dimension];
	return param ? `/usage?${param}=${id}` : "/usage";
}

export function Money({ totals, currency }: { totals: UsageTotals; currency: string }) {
	return (
		<>
			{isPartial(totals) && (
				<span
					title="At least: some calls used a model without a catalog price"
					className="mr-[0.2em] font-normal opacity-50"
				>
					≥
				</span>
			)}
			{formatMoney(totals.cost, currency)}
		</>
	);
}

export function TrendChip({ current, previous }: { current: number; previous: number }) {
	const change = relativeChange(current, previous);
	if (change === null || Math.abs(change) < 0.01) return null;
	const rising = change > 0;
	const Icon = rising ? TrendingUp : TrendingDown;
	return (
		<span
			className={cn(
				"inline-flex items-center gap-1 rounded-full px-1.5 py-px text-[10.5px] font-semibold tabular-nums",
				rising
					? "bg-warning-bg text-warning dark:bg-amber-950/40 dark:text-amber-300"
					: "bg-success-bg text-success dark:bg-emerald-950/40 dark:text-emerald-300",
			)}
		>
			<Icon className="size-3" />
			{formatChange(change)}
		</span>
	);
}

export function TokenBar({ totals }: { totals: UsageTotals }) {
	const total = totals.tokens.total;
	if (total === 0) return null;
	return (
		<div>
			<div className="flex h-1.5 w-full overflow-hidden rounded-full bg-hairline dark:bg-white/10">
				{TOKEN_SEGMENTS.map((segment) => {
					const value = totals.tokens[segment.key];
					if (!value) return null;
					return (
						<span
							key={segment.key}
							className={segment.className}
							style={{ width: `${(value / total) * 100}%` }}
						/>
					);
				})}
			</div>
			<div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
				{TOKEN_SEGMENTS.map((segment) => (
					<div
						key={segment.key}
						className="flex items-center gap-1.5 text-[11px] text-meta"
					>
						<span className={cn("size-1.5 rounded-full", segment.className)} />
						<span>{segment.label}</span>
						<span className="ml-auto font-mono tabular-nums text-subtle dark:text-panel-body">
							{formatTokens(totals.tokens[segment.key])}
						</span>
					</div>
				))}
			</div>
		</div>
	);
}

/** A vendor's logo; a neutral square for models outside the catalog. */
export function VendorMark({ vendor }: { vendor: string | null }) {
	return vendor ? (
		<ModelSelectorLogo provider={vendor} className="size-3.5 shrink-0" />
	) : (
		<span className="size-3.5 shrink-0 rounded-[3px] bg-hairline dark:bg-white/10" />
	);
}

const SPLIT_COLORS = ["#1F5C57", "#3D8B63", "#C27A3A", "#6B7FD7", "#B5547A", "#8A9A92"];

const SPLIT_PERIODS = [
	{ key: "month", label: "Month" },
	{ key: "year", label: "Year" },
	{ key: "allTime", label: "All time" },
] as const;

type SplitPeriod = (typeof SPLIT_PERIODS)[number]["key"];

const MAX_MODELS = 5;

function SplitRows({
	splits,
	period,
	currency,
	colored,
}: {
	splits: UsageSplit[];
	period: SplitPeriod;
	currency: string;
	colored: boolean;
}) {
	const total = splits.reduce((sum, split) => sum + split.summary[period].cost, 0);
	const totalTokens = splits.reduce(
		(sum, split) => sum + split.summary[period].tokens.total,
		0,
	);
	const share = (totals: UsageTotals) =>
		total > 0 ? totals.cost / total : totalTokens > 0 ? totals.tokens.total / totalTokens : 0;
	return (
		<>
			{colored && splits.length > 1 && (
				<div className="mt-2 flex h-1.5 w-full overflow-hidden rounded-full bg-hairline dark:bg-white/10">
					{splits.map((split, index) => (
						<span
							key={split.key ?? "other"}
							style={{
								width: `${share(split.summary[period]) * 100}%`,
								backgroundColor: SPLIT_COLORS[index % SPLIT_COLORS.length],
							}}
						/>
					))}
				</div>
			)}
			<ul className="mt-1.5 space-y-1">
				{splits.map((split, index) => {
					const totals = split.summary[period];
					return (
						<li key={split.key ?? "other"} className="flex items-center gap-2">
							{colored && splits.length > 1 && (
								<span
									className="size-1.5 shrink-0 rounded-full"
									style={{ backgroundColor: SPLIT_COLORS[index % SPLIT_COLORS.length] }}
								/>
							)}
							<VendorMark vendor={split.vendor} />
							<span
								className={cn(
									"min-w-0 flex-1 truncate",
									split.key === null ? "text-meta italic" : "text-subtle dark:text-panel-body",
								)}
							>
								{split.label}
							</span>
							<span className="shrink-0 text-[11px] text-meta tabular-nums">
								{Math.round(share(totals) * 100)}%
							</span>
							<span className="w-16 shrink-0 text-right font-mono font-medium tabular-nums text-foreground">
								<Money totals={totals} currency={currency} />
							</span>
						</li>
					);
				})}
			</ul>
		</>
	);
}

/** Where an entity's spend went, by vendor then by model, over a chosen period. */
function SpendSplit({
	vendors,
	models,
	currency,
}: {
	vendors: UsageSplit[];
	models: UsageSplit[];
	currency: string;
}) {
	const [chosen, setChosen] = useState<SplitPeriod | null>(null);
	const period =
		chosen ??
		SPLIT_PERIODS.find(({ key }) => models.some((model) => model.summary[key].calls > 0))
			?.key ??
		"allTime";
	const rank = (splits: UsageSplit[]) =>
		splits
			.filter((split) => split.summary[period].calls > 0)
			.sort(
				(a, b) =>
					b.summary[period].cost - a.summary[period].cost ||
					b.summary[period].tokens.total - a.summary[period].tokens.total,
			);
	const shownVendors = rank(vendors);
	const ranked = rank(models);
	const shownModels = ranked.slice(0, MAX_MODELS);
	// One vendor with one model says the same thing twice.
	const withVendors = shownVendors.length > 1 || ranked.length > 1;

	return (
		<div className="mt-3 border-t border-border pt-2.5">
			<div className="flex items-center justify-between gap-2">
				<span className="text-[11px] text-meta">
					{withVendors ? "Spend by vendor" : "Model"}
				</span>
				<div className="flex rounded-[6px] bg-hairline p-0.5 dark:bg-white/5">
					{SPLIT_PERIODS.map(({ key, label }) => (
						<button
							key={key}
							type="button"
							className={cn(
								"cursor-pointer rounded-[4px] px-1.5 py-px text-[10.5px] font-semibold transition-colors",
								period === key
									? "bg-card text-foreground shadow-xs dark:bg-white/10"
									: "text-meta hover:text-foreground",
							)}
							onClick={() => {
								setChosen(key);
							}}
						>
							{label}
						</button>
					))}
				</div>
			</div>
			{ranked.length === 0 ? (
				<p className="mt-2 text-meta">No model calls in this period.</p>
			) : withVendors ? (
				<>
					<SplitRows splits={shownVendors} period={period} currency={currency} colored />
					<div className="mt-2.5 text-[11px] text-meta">
						{ranked.length > MAX_MODELS
							? `Top ${MAX_MODELS} of ${ranked.length} models`
							: "By model"}
					</div>
					<SplitRows splits={shownModels} period={period} currency={currency} colored={false} />
				</>
			) : (
				<SplitRows splits={shownModels} period={period} currency={currency} colored={false} />
			)}
		</div>
	);
}

/** Share of the current calendar month already behind us, in (0, 1]. */
function monthElapsed(now = new Date()): number {
	const start = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
	const end = new Date(now.getFullYear(), now.getMonth() + 1, 1).getTime();
	return Math.max((now.getTime() - start) / (end - start), 1 / 31);
}

/** The hover card body: month with trend, then last month, year and all time. */
export function UsageSummaryCard({
	title,
	summary,
	currency,
	scope,
	href,
	split,
	splitLoading = false,
}: {
	title: string;
	summary: UsageSummary;
	currency: string;
	scope: UsageScope;
	href?: string;
	/** Vendor and model split, loaded when the card opens. */
	split?: Pick<UsageSummaryResponse, "vendors" | "models"> | null;
	splitLoading?: boolean;
}) {
	const periods = [
		["Last month", summary.previousMonth],
		["This year", summary.year],
		["All time", summary.allTime],
	] as const;
	const unpriced = summary.allTime.unpricedCalls;
	const elapsed = monthElapsed();
	// Month to date against a full month reads as a drop; compare the pace instead.
	const pace = elapsed < 0.97 ? summary.month.cost / elapsed : summary.month.cost;
	return (
		<div className="text-[12px]">
			<div className="flex items-center justify-between gap-3">
				<span className="truncate font-semibold text-foreground">{title}</span>
				<span className="shrink-0 rounded-[4px] bg-petrol-tint px-1.5 py-px text-[10.5px] font-semibold text-petrol dark:bg-white/10 dark:text-panel-terminal">
					{scope === "personal" ? "Your usage" : "Workspace"}
				</span>
			</div>

			<div className="mt-3 text-[11px] text-meta">This month</div>
			<div className="mt-0.5 flex items-baseline gap-2">
				<span className="font-display text-[24px] font-bold tabular-nums text-foreground">
					<Money totals={summary.month} currency={currency} />
				</span>
				<TrendChip current={pace} previous={summary.previousMonth.cost} />
			</div>
			<div className="mt-0.5 text-[11px] text-meta">
				{formatTokens(summary.month.tokens.total)} tokens /{" "}
				{formatCount(summary.month.calls)} model calls
				{pace !== summary.month.cost && summary.month.cost > 0 && (
					<span className="block">
						On pace for {formatMoney(pace, currency)} this month
					</span>
				)}
			</div>

			{summary.month.tokens.total > 0 && (
				<div className="mt-3">
					<TokenBar totals={summary.month} />
				</div>
			)}

			<table className="mt-3 w-full border-t border-border tabular-nums">
				<tbody>
					{periods.map(([label, totals]) => (
						<tr key={label}>
							<td className="pt-1.5 text-subtle dark:text-panel-body">{label}</td>
							<td className="pt-1.5 text-right text-meta">
								{formatTokens(totals.tokens.total)} tokens
							</td>
							<td className="pt-1.5 pl-3 text-right font-mono font-medium text-foreground">
								<Money totals={totals} currency={currency} />
							</td>
						</tr>
					))}
				</tbody>
			</table>

			{summary.allTime.calls > 0 &&
				(split ? (
					<SpendSplit vendors={split.vendors} models={split.models} currency={currency} />
				) : (
					splitLoading && (
						<div className="mt-3 space-y-1.5 border-t border-border pt-2.5">
							<div className="h-3 w-24 animate-pulse rounded bg-hairline dark:bg-white/10" />
							<div className="h-1.5 w-full animate-pulse rounded-full bg-hairline dark:bg-white/10" />
							<div className="h-3 w-full animate-pulse rounded bg-hairline dark:bg-white/10" />
						</div>
					)
				))}

			{unpriced > 0 && (
				<p className="mt-2.5 leading-[1.45] text-meta">
					{formatCount(unpriced)} of {formatCount(summary.allTime.calls)} calls
					used a model without a catalog price; their tokens are counted but
					not their cost.
				</p>
			)}

			{href && (
				<Link
					href={href}
					className="mt-3 flex items-center justify-between rounded-[7px] border border-input px-2.5 py-1.5 font-semibold text-petrol transition-colors hover:border-border-hover hover:bg-petrol-tint dark:border-white/10 dark:text-panel-terminal dark:hover:bg-white/5"
				>
					View usage over time
					<ArrowRight className="size-3.5" />
				</Link>
			)}
		</div>
	);
}

type BadgeVariant = "chip" | "header" | "pill";

const VARIANT_CLASS: Record<BadgeVariant, string> = {
	chip: "flex h-[30px] max-w-full min-w-0 items-center gap-1.5 rounded-[4px] border border-[#ECF1EE] bg-[#F4F7F5] px-3 text-[12.5px] font-medium text-[#4A5B53] dark:border-white/10 dark:bg-white/5 dark:text-white/80",
	header:
		"flex items-center gap-1.5 whitespace-nowrap rounded-[7px] border border-input bg-card px-3 py-2 text-[13px] font-semibold text-foreground transition-colors hover:border-border-hover dark:border-white/10 dark:bg-white/[0.03] dark:hover:border-white/20",
	pill: "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-[4px] bg-petrol-tint px-[9px] py-[3px] text-[10.5px] font-semibold text-petrol dark:bg-white/10 dark:text-panel-terminal",
};

/**
 * This month's cost of one agent, project, trigger or user, with a hover card
 * covering last month, the year and all time. Reads the batched summaries, so
 * a list of fifty cards costs one request.
 */
export function UsageBadge({
	dimension,
	id,
	title,
	variant = "chip",
	hideWhenEmpty = false,
	className,
}: {
	dimension: UsageEntityDimension;
	id: string;
	title: string;
	variant?: BadgeVariant;
	hideWhenEmpty?: boolean;
	className?: string;
}) {
	const entry = useUsageSummariesStore((state) => state.byDimension[dimension]);
	const ensure = useUsageSummariesStore((state) => state.ensure);
	const detail = useUsageSummariesStore(
		(state) => state.details[detailKey(dimension, id)],
	);
	const ensureDetail = useUsageSummariesStore((state) => state.ensureDetail);

	useEffect(() => {
		ensure(dimension);
	}, [dimension, ensure]);

	const data = entry?.data;
	if (!data) return null;
	const summary = data.items[id] ?? EMPTY_SUMMARY;
	const empty = summary.allTime.calls === 0;
	if (empty && hideWhenEmpty) return null;

	const currency = data.currency.code;
	const label = empty ? (
		"No usage yet"
	) : (
		<>
			<Money totals={summary.month} currency={currency} />
			<span className="font-normal text-meta dark:text-panel-dim">
				{variant === "pill" ? "/mo" : "this month"}
			</span>
		</>
	);

	return (
		<HoverCard
			openDelay={120}
			closeDelay={80}
			onOpenChange={(open) => {
				if (open && !empty) ensureDetail(dimension, id);
			}}
		>
			<HoverCardTrigger asChild>
				<span
					tabIndex={0}
					aria-label={`${title}: usage and cost`}
					className={cn(
						VARIANT_CLASS[variant],
						"cursor-default tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-petrol/40",
						className,
					)}
				>
					{variant !== "pill" && (
						<Coins className="size-[13px] shrink-0 text-[#7C8C84] dark:text-muted-foreground" />
					)}
					<span className="flex min-w-0 items-baseline gap-1 truncate">
						{label}
					</span>
				</span>
			</HoverCardTrigger>
			<HoverCardContent
				align="end"
				className="w-80"
				onClick={(event) => {
					// Portaled, but React still bubbles clicks to clickable cards.
					event.stopPropagation();
				}}
			>
				<UsageSummaryCard
					title={title}
					summary={summary}
					currency={currency}
					scope={data.scope}
					href={usageHref(dimension, id)}
					split={detail?.data}
					splitLoading={detail?.loading ?? true}
				/>
			</HoverCardContent>
		</HoverCard>
	);
}

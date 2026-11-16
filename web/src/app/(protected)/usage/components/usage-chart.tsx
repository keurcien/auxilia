"use client";

import { useMemo, useState } from "react";
import { CHANNEL_META, CHANNEL_ORDER, formatBucket, formatCount, formatMoney, formatTokens } from "@/lib/usage/format";
import { cn } from "@/lib/utils";
import type { UsageChannel, UsageGranularity, UsageSeriesPoint } from "@/types/usage";

export type ChartMetric = "cost" | "tokens";

/** A bucket this many times above the period average gets flagged. */
const SPIKE_FACTOR = 2;
const MAX_X_LABELS = 8;

/** Smallest axis maximum above `value` whose quarters are round numbers. */
function niceCeiling(value: number): number {
	if (value <= 0) return 1;
	const quarter = value / 4;
	const magnitude = 10 ** Math.floor(Math.log10(quarter));
	const step =
		[1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].find((candidate) => candidate * magnitude >= quarter) ?? 10;
	return step * magnitude * 4;
}

function valueOf(point: UsageSeriesPoint, metric: ChartMetric): number {
	return metric === "cost" ? point.cost : point.tokens;
}

export function UsageChart({
	series,
	granularity,
	currency,
	metric,
	lastInProgress,
}: {
	series: UsageSeriesPoint[];
	granularity: UsageGranularity;
	currency: string;
	metric: ChartMetric;
	/** The range ends today, so its last bucket is still filling up. */
	lastInProgress: boolean;
}) {
	const [hovered, setHovered] = useState<number | null>(null);

	const { ceiling, average, channels } = useMemo(() => {
		const values = series.map((point) => valueOf(point, metric));
		const max = Math.max(0, ...values);
		const used = new Set<UsageChannel>();
		for (const point of series) {
			for (const [channel, cost] of Object.entries(point.costByChannel)) {
				if (cost) used.add(channel as UsageChannel);
			}
		}
		return {
			ceiling: niceCeiling(max),
			average: series.length
				? values.reduce((sum, value) => sum + value, 0) / series.length
				: 0,
			channels: CHANNEL_ORDER.filter((channel) => used.has(channel)),
		};
	}, [series, metric]);

	const format = (value: number) =>
		metric === "cost" ? formatMoney(value, currency) : formatTokens(value);
	const labelEvery = Math.max(1, Math.ceil(series.length / MAX_X_LABELS));
	const flagSpikes = series.length >= 7 && average > 0;
	const ticks = [1, 0.75, 0.5, 0.25, 0];
	const point = hovered === null ? null : series[hovered];

	return (
		<div className="flex gap-3">
			<div className="relative flex h-[232px] w-14 shrink-0 flex-col justify-between pb-6 text-right font-mono text-[10.5px] tabular-nums text-meta dark:text-panel-dim">
				{ticks.map((tick) => (
					<span key={tick} className="-translate-y-1/2 leading-none first:translate-y-0 last:translate-y-0">
						{format(ceiling * tick)}
					</span>
				))}
			</div>

			<div className="relative min-w-0 flex-1">
				<div className="relative h-[208px]">
					{ticks.map((tick) => (
						<div
							key={tick}
							className={cn(
								"pointer-events-none absolute inset-x-0 border-t",
								tick === 0
									? "border-border"
									: "border-dashed border-hairline dark:border-white/[0.06]",
							)}
							style={{ bottom: `${tick * 100}%` }}
						/>
					))}
					{average > 0 && (
						<div
							className="pointer-events-none absolute inset-x-0 z-[1] border-t border-dashed border-[#C27A3A]/60"
							style={{ bottom: `${(average / ceiling) * 100}%` }}
						>
							<span className="absolute -top-[9px] right-0 rounded-[3px] bg-canvas px-1 text-[10px] font-semibold text-[#A8662C] dark:bg-card dark:text-amber-300">
								Avg {format(average)}
							</span>
						</div>
					)}

					<div
						className={cn(
							"relative flex h-full items-end",
							series.length > 60 ? "gap-px" : series.length > 24 ? "gap-[3px]" : "gap-1.5",
						)}
						onMouseLeave={() => {
							setHovered(null);
						}}
					>
						{series.map((bucket, index) => {
							const value = valueOf(bucket, metric);
							const height = (value / ceiling) * 100;
							const spike = flagSpikes && value > average * SPIKE_FACTOR;
							const partial = lastInProgress && index === series.length - 1;
							return (
								<div
									key={bucket.start}
									className="group/bar relative flex h-full min-w-0 flex-1 items-end"
									onMouseEnter={() => {
										setHovered(index);
									}}
								>
									<div
										className={cn(
											"absolute inset-x-[-1px] inset-y-0 rounded-[3px] transition-colors",
											hovered === index && "bg-petrol/[0.06] dark:bg-white/[0.05]",
										)}
									/>
									<div
										className={cn(
											"relative flex w-full flex-col-reverse overflow-hidden rounded-t-[3px] transition-opacity",
											hovered !== null && hovered !== index && "opacity-55",
											partial && "opacity-70",
										)}
										style={{ height: `${height}%`, minHeight: value > 0 ? 2 : 0 }}
									>
										{metric === "cost" ? (
											channels.map((channel) => {
												const part = bucket.costByChannel[channel] ?? 0;
												if (!part || !value) return null;
												return (
													<span
														key={channel}
														className="block w-full shrink-0"
														style={{
															height: `${(part / value) * 100}%`,
															backgroundColor: CHANNEL_META[channel].color,
														}}
													/>
												);
											})
										) : (
											<span className="block h-full w-full bg-petrol" />
										)}
									</div>
									{spike && (
										<span
											className="absolute left-1/2 size-1.5 -translate-x-1/2 rounded-full bg-[#C27A3A] ring-2 ring-canvas dark:ring-card"
											style={{ bottom: `calc(${height}% + 5px)` }}
										/>
									)}
								</div>
							);
						})}
					</div>

					{point && hovered !== null && (
						<ChartTooltip
							point={point}
							granularity={granularity}
							currency={currency}
							channels={channels}
							average={average}
							metric={metric}
							position={(hovered + 0.5) / series.length}
							partial={lastInProgress && hovered === series.length - 1}
						/>
					)}
				</div>

				<div className="relative mt-2 h-4 text-[10.5px] text-meta dark:text-panel-dim">
					{series.map((bucket, index) =>
						index % labelEvery === 0 ? (
							<span
								key={bucket.start}
								className="absolute -translate-x-1/2 whitespace-nowrap tabular-nums"
								style={{ left: `${((index + 0.5) / series.length) * 100}%` }}
							>
								{formatBucket(bucket.start, granularity)}
							</span>
						) : null,
					)}
				</div>
			</div>
		</div>
	);
}

function ChartTooltip({
	point,
	granularity,
	currency,
	channels,
	average,
	metric,
	position,
	partial,
}: {
	point: UsageSeriesPoint;
	granularity: UsageGranularity;
	currency: string;
	channels: UsageChannel[];
	average: number;
	metric: ChartMetric;
	position: number;
	partial: boolean;
}) {
	const value = valueOf(point, metric);
	const ratio = average > 0 ? value / average : null;
	const parts = channels
		.map((channel) => ({ channel, cost: point.costByChannel[channel] ?? 0 }))
		.filter((part) => part.cost > 0)
		.sort((a, b) => b.cost - a.cost);
	// Beside the bar, never over it: right of it in the left half, left of it otherwise.
	const right = position < 0.5;

	return (
		<div
			className={cn(
				"pointer-events-none absolute top-1 z-10 w-60 rounded-[10px] border border-hairline bg-canvas p-3 text-[12px] shadow-[0_12px_32px_-12px_rgba(10,25,30,0.3)] dark:border-white/10 dark:bg-card",
				!right && "-translate-x-full",
			)}
			style={{ left: `calc(${position * 100}% ${right ? "+" : "-"} 14px)` }}
		>
			<div className="flex items-center justify-between gap-2">
				<span className="font-semibold text-foreground">
					{formatBucket(point.start, granularity, "long")}
				</span>
				{partial && <span className="text-[10.5px] text-meta">In progress</span>}
			</div>
			<div className="mt-1.5 flex items-baseline gap-2">
				<span className="font-display text-[20px] font-bold tabular-nums text-foreground">
					{formatMoney(point.cost, currency)}
				</span>
				{ratio !== null && value > 0 && (
					<span
						className={cn(
							"text-[11px] font-semibold tabular-nums",
							ratio > SPIKE_FACTOR ? "text-[#A8662C] dark:text-amber-300" : "text-meta",
						)}
					>
						{ratio >= 1
							? `${ratio.toFixed(1)}x average`
							: `${Math.round(ratio * 100)}% of average`}
					</span>
				)}
			</div>
			<div className="mt-0.5 text-[11px] text-meta">
				{formatTokens(point.tokens)} tokens / {formatCount(point.calls)} model calls
			</div>
			{parts.length > 0 && (
				<div className="mt-2.5 space-y-1 border-t border-border pt-2">
					{parts.map(({ channel, cost }) => (
						<div key={channel} className="flex items-center gap-2">
							<span
								className="size-2 shrink-0 rounded-[2px]"
								style={{ backgroundColor: CHANNEL_META[channel].color }}
							/>
							<span className="truncate text-subtle dark:text-panel-body">
								{CHANNEL_META[channel].label}
							</span>
							<span className="ml-auto font-mono tabular-nums text-foreground">
								{formatMoney(cost, currency)}
							</span>
						</div>
					))}
				</div>
			)}
		</div>
	);
}

export function ChannelLegend({
	rows,
	currency,
}: {
	rows: { channel: UsageChannel; cost: number; share: number }[];
	currency: string;
}) {
	return (
		<div className="flex flex-wrap gap-x-4 gap-y-1.5">
			{rows.map(({ channel, cost, share }) => (
				<span key={channel} className="flex items-center gap-1.5 text-[12px] text-subtle dark:text-panel-body">
					<span
						className="size-2 rounded-[2px]"
						style={{ backgroundColor: CHANNEL_META[channel].color }}
					/>
					{CHANNEL_META[channel].label}
					<span className="font-mono tabular-nums text-foreground">
						{formatMoney(cost, currency)}
					</span>
					<span className="tabular-nums text-meta">{Math.round(share * 100)}%</span>
				</span>
			))}
		</div>
	);
}

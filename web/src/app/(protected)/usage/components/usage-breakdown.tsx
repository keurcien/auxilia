"use client";

import { useState } from "react";
import { ChevronRight, Flame, TrendingUp } from "lucide-react";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { TrendChip, VendorMark } from "@/components/usage/usage-badge";
import {
	CHANNEL_META,
	formatChange,
	formatCount,
	formatMoney,
	formatTokens,
	relativeChange,
} from "@/lib/usage/format";
import { cn } from "@/lib/utils";
import type { UsageBreakdownRow, UsageChannel, UsageDimension } from "@/types/usage";

export type FilterDimension = "agent" | "project" | "trigger" | "user" | "channel";

const FILTERABLE = new Set<UsageDimension>(["agent", "project", "trigger", "user", "channel"]);

export const DIMENSION_LABELS: Record<UsageDimension, { tab: string; singular: string }> = {
	channel: { tab: "Channels", singular: "Channel" },
	agent: { tab: "Agents", singular: "Agent" },
	project: { tab: "Projects", singular: "Project" },
	trigger: { tab: "Triggers", singular: "Trigger" },
	user: { tab: "Users", singular: "User" },
	model: { tab: "Models", singular: "Model" },
	vendor: { tab: "Vendors", singular: "Vendor" },
	workspace: { tab: "Workspaces", singular: "Workspace" },
};

const TAB_ORDER: UsageDimension[] = [
	"channel",
	"agent",
	"project",
	"trigger",
	"user",
	"model",
	"vendor",
	"workspace",
];

const COLLAPSED_ROWS = 10;

export function UsageBreakdown({
	breakdowns,
	currency,
	dimension,
	onDimensionChange,
	onSelect,
	activeFilters,
	showChange,
}: {
	breakdowns: Partial<Record<UsageDimension, UsageBreakdownRow[]>>;
	currency: string;
	dimension: UsageDimension;
	onDimensionChange: (dimension: UsageDimension) => void;
	onSelect: (dimension: FilterDimension, key: string) => void;
	activeFilters: Partial<Record<FilterDimension, string>>;
	/** False when there is no previous period to compare with (all time). */
	showChange: boolean;
}) {
	const [expanded, setExpanded] = useState(false);
	const available = TAB_ORDER.filter((key) => breakdowns[key] !== undefined);
	const current = available.includes(dimension) ? dimension : (available[0] ?? "channel");
	const rows = breakdowns[current] ?? [];
	const visible = expanded ? rows : rows.slice(0, COLLAPSED_ROWS);
	const maxShare = Math.max(0, ...rows.map((row) => row.share));
	const filterable = FILTERABLE.has(current);

	return (
		<section className="rounded-2xl border border-[#E9EEEB] bg-white dark:border-white/10 dark:bg-card">
			<div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2 border-b border-[#F0F3F1] px-5 pt-4 dark:border-white/5">
				<div className="pb-3">
					<h2 className="text-[15px] font-bold text-foreground">Where the spend goes</h2>
					<p className="mt-0.5 text-[12.5px] text-meta dark:text-panel-dim">
						{filterable
							? "Select a row to focus the whole page on it."
							: "Ranked by cost over the selected period."}
					</p>
				</div>
				<UnderlineTabs
					tabs={available.map((key) => ({
						key,
						label: DIMENSION_LABELS[key].tab,
						count: breakdowns[key]?.length ?? 0,
					}))}
					value={current}
					onChange={(key) => {
						setExpanded(false);
						onDimensionChange(key);
					}}
				/>
			</div>

			{rows.length === 0 ? (
				<p className="px-5 py-10 text-center text-[13px] text-meta">
					{current === "trigger"
						? "No trigger ran a model in this period."
						: "Nothing to break down in this period."}
				</p>
			) : (
				<div className="overflow-x-auto">
					<table className="w-full min-w-[640px] text-[13px] tabular-nums">
						<thead>
							<tr className="text-left text-[11.5px] font-medium text-meta dark:text-panel-dim">
								<th className="py-2.5 pr-3 pl-5 font-medium">{DIMENSION_LABELS[current].singular}</th>
								<th className="w-[28%] px-3 py-2.5 font-medium">Share of spend</th>
								<th className="px-3 py-2.5 text-right font-medium">Tokens</th>
								<th className="px-3 py-2.5 text-right font-medium">Calls</th>
								<th className="px-3 py-2.5 text-right font-medium">Cost</th>
								{showChange && (
									<th className="py-2.5 pr-5 pl-3 text-right font-medium">Change</th>
								)}
							</tr>
						</thead>
						<tbody>
							{visible.map((row) => {
								const selectable = filterable && row.key !== null;
								const active =
									row.key !== null &&
									activeFilters[current as FilterDimension] === row.key;
								const color =
									current === "channel" && row.key
										? CHANNEL_META[row.key as UsageChannel]?.color
										: undefined;
								return (
									<tr
										key={row.key ?? "none"}
										className={cn(
											"group border-t border-[#F0F3F1] dark:border-white/5",
											selectable && "cursor-pointer hover:bg-[#F7FAF8] dark:hover:bg-white/[0.03]",
											active && "bg-petrol-tint/60 dark:bg-white/[0.05]",
										)}
										onClick={
											selectable
												? () => {
														onSelect(current as FilterDimension, row.key as string);
													}
												: undefined
										}
									>
										<td className="max-w-[280px] py-2.5 pr-3 pl-5">
											<div className="flex min-w-0 items-center gap-2">
												{color && (
													<span className="size-2 shrink-0 rounded-[2px]" style={{ backgroundColor: color }} />
												)}
												{(current === "model" || current === "vendor") && (
													<VendorMark vendor={row.vendor ?? null} />
												)}
												<span
													className={cn(
														"truncate font-medium",
														row.key === null ? "text-meta italic" : "text-foreground",
													)}
												>
													{row.label}
												</span>
												{selectable && (
													<ChevronRight className="size-3.5 shrink-0 text-ghost opacity-0 transition-opacity group-hover:opacity-100" />
												)}
											</div>
										</td>
										<td className="px-3 py-2.5">
											<div className="flex items-center gap-2.5">
												<div className="h-1.5 flex-1 overflow-hidden rounded-full bg-hairline dark:bg-white/10">
													<div
														className="h-full rounded-full bg-petrol"
														style={{
															width: `${maxShare > 0 ? (row.share / maxShare) * 100 : 0}%`,
															backgroundColor: color,
														}}
													/>
												</div>
												<span className="w-10 text-right text-[12px] text-meta">
													{row.share >= 0.001 ? `${(row.share * 100).toFixed(row.share < 0.1 ? 1 : 0)}%` : "0%"}
												</span>
											</div>
										</td>
										<td className="px-3 py-2.5 text-right text-subtle dark:text-panel-body">
											{formatTokens(row.tokens)}
										</td>
										<td className="px-3 py-2.5 text-right text-subtle dark:text-panel-body">
											{formatCount(row.calls)}
										</td>
										<td className="px-3 py-2.5 text-right font-mono font-medium text-foreground">
											{row.unpricedCalls > 0 && row.unpricedCalls === row.calls
												? "Not priced"
												: formatMoney(row.cost, currency)}
										</td>
										{showChange && (
											<td className="py-2.5 pr-5 pl-3 text-right">
												{row.previousCost <= 0 && row.cost > 0 ? (
													<span className="text-[11px] font-semibold text-petrol dark:text-panel-terminal">New</span>
												) : (
													<TrendChip current={row.cost} previous={row.previousCost} />
												)}
											</td>
										)}
									</tr>
								);
							})}
						</tbody>
					</table>
					{rows.length > COLLAPSED_ROWS && (
						<button
							type="button"
							className="w-full cursor-pointer border-t border-[#F0F3F1] py-2.5 text-[12.5px] font-semibold text-petrol transition-colors hover:bg-[#F7FAF8] dark:border-white/5 dark:text-panel-terminal dark:hover:bg-white/[0.03]"
							onClick={() => {
								setExpanded((value) => !value);
							}}
						>
							{expanded ? "Show fewer" : `Show all ${rows.length}`}
						</button>
					)}
				</div>
			)}
		</section>
	);
}

interface Mover {
	dimension: FilterDimension;
	key: string;
	label: string;
	cost: number;
	previousCost: number;
	delta: number;
}

/** Entities whose spend grew the most against the previous period. */
export function RisingUsage({
	breakdowns,
	currency,
	totalCost,
	previousLabel,
	onSelect,
}: {
	breakdowns: Partial<Record<UsageDimension, UsageBreakdownRow[]>>;
	currency: string;
	totalCost: number;
	previousLabel: string;
	onSelect: (dimension: FilterDimension, key: string) => void;
}) {
	const dimensions: FilterDimension[] = ["agent", "trigger", "project", "user"];
	const movers: Mover[] = dimensions
		.flatMap((dimension) =>
			(breakdowns[dimension] ?? []).map((row) => ({
				dimension,
				key: row.key ?? "",
				label: row.label,
				cost: row.cost,
				previousCost: row.previousCost,
				delta: row.cost - row.previousCost,
			})),
		)
		.filter((mover) => {
			if (!mover.key || mover.delta <= 0) return false;
			// A row holding all of the spend only mirrors the page filter.
			if (mover.cost >= totalCost * 0.999) return false;
			// Ignore noise: a change must matter against the period's spend.
			if (mover.delta < totalCost * 0.02) return false;
			return mover.previousCost <= 0 || mover.delta / mover.previousCost >= 0.25;
		})
		.sort((a, b) => b.delta - a.delta)
		.slice(0, 5);

	return (
		<section className="flex flex-col rounded-2xl border border-[#E9EEEB] bg-white p-5 dark:border-white/10 dark:bg-card">
			<div className="flex items-center gap-2">
				<Flame className="size-4 text-[#C27A3A]" />
				<h2 className="text-[15px] font-bold text-foreground">Biggest increases</h2>
			</div>
			<p className="mt-0.5 text-[12.5px] text-meta dark:text-panel-dim">
				Compared with {previousLabel}.
			</p>
			{movers.length === 0 ? (
				<div className="flex flex-1 flex-col items-center justify-center gap-2 py-8 text-center">
					<TrendingUp className="size-5 text-ghost" />
					<p className="max-w-[240px] text-[12.5px] text-meta">
						No agent, trigger, project or user stands out against the previous
						period.
					</p>
				</div>
			) : (
				<ul className="mt-3 space-y-1">
					{movers.map((mover) => {
						const change = relativeChange(mover.cost, mover.previousCost);
						return (
							<li key={`${mover.dimension}-${mover.key}`}>
								<button
									type="button"
									className="flex w-full cursor-pointer items-center gap-3 rounded-[8px] px-2 py-2 text-left transition-colors hover:bg-[#F7FAF8] dark:hover:bg-white/[0.04]"
									onClick={() => {
										onSelect(mover.dimension, mover.key);
									}}
								>
									<div className="min-w-0 flex-1">
										<div className="truncate text-[13px] font-semibold text-foreground">{mover.label}</div>
										<div className="text-[11.5px] text-meta">
											{DIMENSION_LABELS[mover.dimension].singular} /{" "}
											{formatMoney(mover.previousCost, currency)} then{" "}
											{formatMoney(mover.cost, currency)}
										</div>
									</div>
									<div className="shrink-0 text-right">
										<div className="font-mono text-[13px] font-semibold tabular-nums text-[#A8662C] dark:text-amber-300">
											+{formatMoney(mover.delta, currency)}
										</div>
										<div className="text-[11px] tabular-nums text-meta">
											{change === null ? "New" : formatChange(change)}
										</div>
									</div>
								</button>
							</li>
						);
					})}
				</ul>
			)}
		</section>
	);
}

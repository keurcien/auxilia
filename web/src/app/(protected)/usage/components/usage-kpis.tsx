"use client";

import { Gauge } from "lucide-react";
import { Money, TokenBar, TrendChip } from "@/components/usage/usage-badge";
import { formatCount, formatMoney, formatTokens } from "@/lib/usage/format";
import { cn } from "@/lib/utils";
import type { UsageBudget, UsageTotals } from "@/types/usage";

const CARD =
	"flex min-w-0 flex-col rounded-2xl border border-[#E9EEEB] bg-white p-5 dark:border-white/10 dark:bg-card";

function Kpi({
	label,
	value,
	current,
	previous,
	children,
}: {
	label: string;
	value: React.ReactNode;
	current?: number;
	previous?: number;
	children?: React.ReactNode;
}) {
	return (
		<div className={CARD}>
			<div className="text-[12.5px] font-medium text-meta dark:text-panel-dim">{label}</div>
			<div className="mt-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
				<span className="font-display text-[28px] leading-none font-bold tabular-nums text-foreground">
					{value}
				</span>
				{current !== undefined && previous !== undefined && (
					<TrendChip current={current} previous={previous} />
				)}
			</div>
			<div className="mt-auto pt-3 text-[12px] leading-[1.5] text-meta dark:text-panel-dim">
				{children}
			</div>
		</div>
	);
}

export function UsageKpis({
	totals,
	previousTotals,
	currency,
	days,
	compare,
	previousLabel,
	budget,
	canManage,
	onSetBudget,
}: {
	totals: UsageTotals;
	previousTotals: UsageTotals;
	currency: string;
	days: number;
	/** False for all time: there is no previous period. */
	compare: boolean;
	previousLabel: string;
	budget: UsageBudget | null;
	canManage: boolean;
	onSetBudget: () => void;
}) {
	const perCall = totals.calls ? totals.cost / totals.calls : 0;
	return (
		<div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
			<Kpi
				label="Spend"
				value={<Money totals={totals} currency={currency} />}
				current={compare ? totals.cost : undefined}
				previous={compare ? previousTotals.cost : undefined}
			>
				{compare ? (
					<>
						<Money totals={previousTotals} currency={currency} /> over {previousLabel}
					</>
				) : (
					<>{formatMoney(totals.cost / Math.max(days, 1), currency)} per day on average</>
				)}
			</Kpi>
			<Kpi
				label="Tokens"
				value={formatTokens(totals.tokens.total)}
				current={compare ? totals.tokens.total : undefined}
				previous={compare ? previousTotals.tokens.total : undefined}
			>
				<TokenBar totals={totals} />
			</Kpi>
			<Kpi
				label="Model calls"
				value={formatCount(totals.calls)}
				current={compare ? totals.calls : undefined}
				previous={compare ? previousTotals.calls : undefined}
			>
				{totals.calls > 0 ? (
					<>
						{formatMoney(perCall, currency)} and{" "}
						{formatTokens(Math.round(totals.tokens.total / totals.calls))} tokens per call
						{totals.unpricedCalls > 0 && (
							<span className="block">
								{formatCount(totals.unpricedCalls)} calls on models without a price
							</span>
						)}
					</>
				) : (
					"No model calls in this period"
				)}
			</Kpi>
			{budget ? (
				<BudgetCard budget={budget} currency={currency} />
			) : (
				<Kpi
					label="Daily average"
					value={formatMoney(totals.cost / Math.max(days, 1), currency)}
				>
					{canManage ? (
						<button
							type="button"
							className="flex cursor-pointer items-center gap-1.5 font-semibold text-petrol hover:underline dark:text-panel-terminal"
							onClick={onSetBudget}
						>
							<Gauge className="size-3.5" />
							Set a monthly budget
						</button>
					) : (
						`Over ${days} ${days === 1 ? "day" : "days"}`
					)}
				</Kpi>
			)}
		</div>
	);
}

function BudgetCard({ budget, currency }: { budget: UsageBudget; currency: string }) {
	const used = budget.monthToDate / budget.monthly;
	const projected = budget.projected / budget.monthly;
	const tone = used >= 1 ? "over" : projected > 1 ? "risk" : "ok";
	const barClass = {
		over: "bg-[#B04A3A]",
		risk: "bg-[#C27A3A]",
		ok: "bg-petrol",
	}[tone];

	return (
		<div className={CARD}>
			<div className="flex items-center justify-between gap-2">
				<span className="text-[12.5px] font-medium text-meta dark:text-panel-dim">Monthly budget</span>
				<span
					className={cn(
						"rounded-full px-2 py-px text-[10.5px] font-semibold",
						tone === "over" && "bg-[#B04A3A]/10 text-[#B04A3A] dark:text-red-300",
						tone === "risk" && "bg-warning-bg text-warning dark:bg-amber-950/40 dark:text-amber-300",
						tone === "ok" && "bg-success-bg text-success dark:bg-emerald-950/40 dark:text-emerald-300",
					)}
				>
					{tone === "over" ? "Over budget" : tone === "risk" ? "On track to exceed" : "On track"}
				</span>
			</div>
			<div className="mt-1.5 flex items-baseline gap-1.5">
				<span className="font-display text-[28px] leading-none font-bold tabular-nums text-foreground">
					{formatMoney(budget.monthToDate, currency)}
				</span>
				<span className="text-[13px] tabular-nums text-meta">
					of {formatMoney(budget.monthly, currency)}
				</span>
			</div>
			<div className="mt-auto pt-3">
				<div className="relative h-2 overflow-hidden rounded-full bg-hairline dark:bg-white/10">
					<div
						className={cn("absolute inset-y-0 left-0 rounded-full opacity-25", barClass)}
						style={{ width: `${Math.min(projected, 1) * 100}%` }}
					/>
					<div
						className={cn("absolute inset-y-0 left-0 rounded-full", barClass)}
						style={{ width: `${Math.min(used, 1) * 100}%` }}
					/>
				</div>
				<div className="mt-2 flex justify-between text-[12px] tabular-nums text-meta dark:text-panel-dim">
					<span>{Math.round(used * 100)}% used</span>
					<span>Projected {formatMoney(budget.projected, currency)}</span>
				</div>
			</div>
		</div>
	);
}

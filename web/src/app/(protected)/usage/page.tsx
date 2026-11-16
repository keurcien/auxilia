"use client";

import { useEffect, useState } from "react";
import { CalendarRange, ChevronDown, History, RotateCw, Settings2, X } from "lucide-react";
import { WorkspacePage } from "@/components/layout/workspace-page";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { getApiErrorMessage } from "@/lib/api/errors";
import { getUsageReport } from "@/lib/api/resources/usage";
import { CHANNEL_META, formatMoney, formatRange, isoDate, parseIsoDate } from "@/lib/usage/format";
import { cn } from "@/lib/utils";
import { useUsageSummariesStore } from "@/stores/usage-summaries-store";
import { useUserStore } from "@/stores/user-store";
import { useWorkspacesStore } from "@/stores/workspaces-store";
import type {
	UsageChannel,
	UsageDimension,
	UsageGranularity,
	UsageReport,
	UsageScope,
} from "@/types/usage";
import {
	DIMENSION_LABELS,
	type FilterDimension,
	RisingUsage,
	UsageBreakdown,
} from "./components/usage-breakdown";
import { type ChartMetric, ChannelLegend, UsageChart } from "./components/usage-chart";
import { UsageFilterSearch } from "./components/usage-filter-search";
import { UsageKpis } from "./components/usage-kpis";
import { UsageSettingsDialog } from "./components/usage-settings-dialog";
import {
	GRANULARITY_LABELS,
	parsePreset,
	presetDates,
	presetGranularities,
	RANGE_PRESETS,
	rangeDays,
} from "./range";

const FILTER_DIMENSIONS: FilterDimension[] = [
	"project",
	"vendor",
	"model",
	"user",
	"agent",
	"trigger",
	"channel",
];

const SCOPE_LABELS: Record<UsageScope, string> = {
	personal: "My usage",
	workspace: "Workspace",
	instance: "All workspaces",
};

const PANEL =
	"rounded-2xl border border-[#E9EEEB] bg-white dark:border-white/10 dark:bg-card";

function Segmented<K extends string>({
	options,
	value,
	onChange,
	label,
}: {
	options: { key: K; label: string }[];
	value: K;
	onChange: (key: K) => void;
	label: string;
}) {
	return (
		<div
			role="radiogroup"
			aria-label={label}
			className="flex shrink-0 rounded-[8px] border border-input bg-[#F4F7F5] p-0.5 dark:border-white/10 dark:bg-white/[0.04]"
		>
			{options.map((option) => (
				<button
					key={option.key}
					type="button"
					role="radio"
					aria-checked={option.key === value}
					className={cn(
						"cursor-pointer whitespace-nowrap rounded-[6px] px-2.5 py-1 text-[12.5px] font-medium transition-colors",
						option.key === value
							? "bg-white text-foreground shadow-[0_1px_2px_rgba(20,30,25,0.08)] dark:bg-white/10"
							: "text-meta hover:text-foreground dark:text-panel-dim",
					)}
					onClick={() => {
						onChange(option.key);
					}}
				>
					{option.label}
				</button>
			))}
		</div>
	);
}

function useFilters() {
	const [agent, setAgent] = useQueryParamState("agent");
	const [project, setProject] = useQueryParamState("project");
	const [trigger, setTrigger] = useQueryParamState("trigger");
	const [user, setUser] = useQueryParamState("user");
	const [channel, setChannel] = useQueryParamState("channel");
	const [model, setModel] = useQueryParamState("model");
	const [vendor, setVendor] = useQueryParamState("vendor");
	const values: Record<FilterDimension, string> = {
		agent,
		project,
		trigger,
		user,
		channel,
		model,
		vendor,
	};
	const setters: Record<FilterDimension, (value: string) => void> = {
		agent: setAgent,
		project: setProject,
		trigger: setTrigger,
		user: setUser,
		channel: setChannel,
		model: setModel,
		vendor: setVendor,
	};
	return { values, setters };
}

export default function UsagePage() {
	const user = useUserStore((state) => state.user);
	const workspaceId = useWorkspacesStore((state) => state.activeWorkspaceId);
	const invalidateSummaries = useUsageSummariesStore((state) => state.invalidate);
	const isAdmin = user?.role === "admin";
	const isInstanceOwner = user?.isInstanceOwner ?? false;

	const [rangeParam, setRangeParam] = useQueryParamState("range");
	const preset = parsePreset(rangeParam);
	const granularities = presetGranularities(preset);
	const [intervalParam, setIntervalParam] = useQueryParamState("interval");
	const granularity = granularities.includes(intervalParam as UsageGranularity)
		? (intervalParam as UsageGranularity)
		: granularities[0];
	const [scopeParam, setScopeParam] = useQueryParamState("scope");
	const scopeOptions: UsageScope[] = [
		...(isAdmin ? (["workspace", "personal"] as const) : []),
		...(isInstanceOwner ? (["instance"] as const) : []),
	];
	const requestedScope = scopeOptions.includes(scopeParam as UsageScope)
		? (scopeParam as UsageScope)
		: undefined;
	const [view, setView] = useQueryParamState("view", "channel");
	const { values: filters, setters: setFilter } = useFilters();
	const [metric, setMetric] = useState<ChartMetric>("cost");

	const [report, setReport] = useState<UsageReport | null>(null);
	const [error, setError] = useState<string | null>(null);
	const [reloadKey, setReloadKey] = useState(0);
	const [settingsOpen, setSettingsOpen] = useState(false);
	const requestKey = [
		preset,
		granularity,
		requestedScope,
		...FILTER_DIMENSIONS.map((dimension) => filters[dimension]),
		workspaceId,
		reloadKey,
	].join("|");
	const [settledKey, setSettledKey] = useState<string | null>(null);
	const loading = settledKey !== requestKey;

	useEffect(() => {
		let cancelled = false;
		getUsageReport({
			...presetDates(preset),
			granularity,
			scope: requestedScope,
			agentId: filters.agent || undefined,
			projectId: filters.project || undefined,
			triggerId: filters.trigger || undefined,
			userId: filters.user || undefined,
			channel: (filters.channel || undefined) as UsageChannel | undefined,
			modelId: filters.model || undefined,
			vendor: filters.vendor || undefined,
		})
			.then((next) => {
				if (cancelled) return;
				setReport(next);
				setError(null);
			})
			.catch((caught: unknown) => {
				if (cancelled) return;
				setError(getApiErrorMessage(caught, "Failed to load usage."));
			})
			.finally(() => {
				if (!cancelled) setSettledKey(requestKey);
			});
		return () => {
			cancelled = true;
		};
		// `requestKey` covers every input of the request.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [requestKey]);

	const scope = report?.scope ?? requestedScope ?? (isAdmin ? "workspace" : "personal");
	const currency = report?.currency.code ?? "EUR";
	const days = report ? rangeDays(report.start, report.end) : 0;
	const compare = preset !== "all";
	const previousLabel = `the previous ${days} ${days === 1 ? "day" : "days"}`;
	const today = isoDate(new Date());
	const presetLabel = RANGE_PRESETS.find((option) => option.key === preset)?.label ?? "";

	const activeFilters = FILTER_DIMENSIONS.filter((dimension) => filters[dimension]).map(
		(dimension) => {
			const id = filters[dimension];
			const label =
				dimension === "channel"
					? (CHANNEL_META[id as UsageChannel]?.label ?? id)
					: (report?.filterLabels[dimension] ??
						report?.breakdowns[dimension]?.find((row) => row.key === id)?.label);
			return {
				dimension,
				label: label ?? `Unknown ${DIMENSION_LABELS[dimension].singular.toLowerCase()}`,
			};
		},
	);

	const selectFilter = (dimension: FilterDimension, key: string) => {
		setFilter[dimension](filters[dimension] === key ? "" : key);
	};

	const channelLegend = (report?.breakdowns.channel ?? [])
		.filter((row) => row.key && row.cost > 0)
		.map((row) => ({ channel: row.key as UsageChannel, cost: row.cost, share: row.share }));

	return (
		<WorkspacePage
			slug="usage"
			title="Usage"
			intro={
				scope === "personal"
					? "Tokens and estimated cost of your model calls, from chats, triggers and integrations."
					: "Tokens and estimated cost of every model call, by channel, agent, project and trigger. Spot what really consumes and keep the budget in check."
			}
			fullWidth
			actions={
				isAdmin ? (
					<button
						type="button"
						className="flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] border border-input px-3 py-2 text-[13px] font-semibold text-foreground transition-colors hover:border-border-hover dark:border-white/10 dark:hover:border-white/20"
						onClick={() => {
							setSettingsOpen(true);
						}}
					>
						<Settings2 className="size-3.5" />
						<span className="hidden sm:inline">Currency and budget</span>
					</button>
				) : undefined
			}
			headerRight={
				<div className="flex w-full flex-wrap items-center gap-2 lg:justify-end">
					<UsageFilterSearch
						scope={requestedScope}
						currency={currency}
						activeFilters={filters}
						onSelect={selectFilter}
					/>
					{scopeOptions.length > 1 && (
						<Segmented
							label="Scope"
							options={scopeOptions.map((key) => ({ key, label: SCOPE_LABELS[key] }))}
							value={scope}
							onChange={(key) => {
								setScopeParam(key === "workspace" ? "" : key);
							}}
						/>
					)}
					<DropdownMenu
						align="end"
						items={RANGE_PRESETS.map((option) => ({
							label: option.label,
							active: option.key === preset,
							onClick: () => {
								setRangeParam(option.key === "30d" ? "" : option.key);
								setIntervalParam("");
							},
						}))}
						trigger={
							<button
								type="button"
								className="flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-[8px] border border-input px-3 py-[7px] text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover data-[state=open]:border-border-hover dark:border-white/10"
							>
								<CalendarRange className="size-3.5 text-meta" />
								{presetLabel}
								<ChevronDown className="size-3.5 text-meta" />
							</button>
						}
					/>
					<Segmented
						label="Interval"
						options={granularities
							.slice()
							.sort((a, b) => ["day", "week", "month"].indexOf(a) - ["day", "week", "month"].indexOf(b))
							.map((key) => ({ key, label: GRANULARITY_LABELS[key] }))}
						value={granularity}
						onChange={(key) => {
							setIntervalParam(key === granularities[0] ? "" : key);
						}}
					/>
				</div>
			}
		>
			<div className={cn("space-y-4 transition-opacity", loading && report && "opacity-60")}>
				{(activeFilters.length > 0 || report) && (
					<div className="flex min-h-7 flex-wrap items-center gap-2 text-[12.5px] text-meta dark:text-panel-dim">
						{report && (
							<span className="tabular-nums">
								{formatRange(report.start, report.end)}
							</span>
						)}
						{activeFilters.map((filter) => (
							<span
								key={filter.dimension}
								className="flex items-center gap-1 rounded-full border border-petrol/25 bg-petrol-tint py-0.5 pr-1 pl-2.5 font-medium text-petrol dark:border-white/15 dark:bg-white/10 dark:text-panel-terminal"
							>
								{DIMENSION_LABELS[filter.dimension].singular}: {filter.label}
								<button
									type="button"
									aria-label={`Remove ${DIMENSION_LABELS[filter.dimension].singular.toLowerCase()} filter`}
									className="flex size-5 cursor-pointer items-center justify-center rounded-full hover:bg-petrol/10"
									onClick={() => {
										setFilter[filter.dimension]("");
									}}
								>
									<X className="size-3" />
								</button>
							</span>
						))}
						{activeFilters.length > 1 && (
							<button
								type="button"
								className="cursor-pointer font-semibold text-petrol hover:underline dark:text-panel-terminal"
								onClick={() => {
									for (const dimension of FILTER_DIMENSIONS) setFilter[dimension]("");
								}}
							>
								Clear all
							</button>
						)}
					</div>
				)}

				{report && !report.backfillCompleted && (
					<div className="flex items-center gap-2.5 rounded-[10px] border border-petrol/20 bg-petrol-tint px-4 py-2.5 text-[13px] text-petrol dark:border-white/10 dark:bg-white/5 dark:text-panel-terminal">
						<History className="size-4 shrink-0" />
						Importing usage from past conversations. Totals before tracking
						started may still grow.
					</div>
				)}

				{error && !report ? (
					<div className={cn(PANEL, "flex flex-col items-center gap-3 px-6 py-14 text-center")}>
						<p className="text-[13.5px] text-body dark:text-panel-body">{error}</p>
						<button
							type="button"
							className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input px-3 py-1.5 text-[13px] font-semibold text-foreground hover:border-border-hover"
							onClick={() => {
								setReloadKey((key) => key + 1);
							}}
						>
							<RotateCw className="size-3.5" />
							Try again
						</button>
					</div>
				) : !report ? (
					<UsageSkeleton />
				) : (
					<>
						<UsageKpis
							totals={report.totals}
							previousTotals={report.previousTotals}
							currency={currency}
							days={days}
							compare={compare}
							previousLabel={previousLabel}
							// The budget covers the whole workspace, not a filtered slice.
							budget={activeFilters.length === 0 ? report.budget : null}
							canManage={isAdmin && scope === "workspace" && activeFilters.length === 0}
							onSetBudget={() => {
								setSettingsOpen(true);
							}}
						/>

						<div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
							<section className={cn(PANEL, "min-w-0 p-5")}>
								<div className="mb-5 flex flex-wrap items-start justify-between gap-3">
									<div>
										<h2 className="text-[15px] font-bold text-foreground">
											{metric === "cost" ? "Spend over time" : "Tokens over time"}
										</h2>
										<p className="mt-0.5 text-[12.5px] text-meta dark:text-panel-dim">
											{GRANULARITY_LABELS[granularity]} totals.{" "}
											{metric === "cost"
												? "Bars are split by channel; dots mark periods above twice the average."
												: "Dots mark periods above twice the average."}
										</p>
									</div>
									<Segmented
										label="Chart metric"
										options={[
											{ key: "cost", label: "Cost" },
											{ key: "tokens", label: "Tokens" },
										]}
										value={metric}
										onChange={setMetric}
									/>
								</div>
								{report.totals.calls === 0 ? (
									<div className="flex h-[232px] flex-col items-center justify-center gap-1 text-center">
										<p className="text-[14px] font-semibold text-foreground">
											No model calls in this period
										</p>
										<p className="max-w-[340px] text-[12.5px] text-meta">
											Usage appears here as soon as an agent answers in a chat,
											a trigger runs or someone talks to it from Slack.
										</p>
									</div>
								) : (
									<>
										<UsageChart
											series={report.series}
											granularity={granularity}
											currency={currency}
											metric={metric}
											lastInProgress={report.end === today}
										/>
										{metric === "cost" && channelLegend.length > 0 && (
											<div className="mt-4 border-t border-[#F0F3F1] pt-3.5 dark:border-white/5">
												<ChannelLegend rows={channelLegend} currency={currency} />
											</div>
										)}
									</>
								)}
							</section>

							{compare ? (
								<RisingUsage
									breakdowns={report.breakdowns}
									currency={currency}
									totalCost={report.totals.cost}
									previousLabel={previousLabel}
									onSelect={selectFilter}
								/>
							) : (
								<TopSpenders report={report} currency={currency} onSelect={selectFilter} />
							)}
						</div>

						<UsageBreakdown
							breakdowns={report.breakdowns}
							currency={currency}
							dimension={view as UsageDimension}
							onDimensionChange={(next) => {
								setView(next);
							}}
							onSelect={selectFilter}
							activeFilters={filters}
							showChange={compare}
						/>

						<p className="max-w-[760px] text-[12px] leading-[1.6] text-meta dark:text-panel-dim">
							Costs are estimates from catalog model prices
							{report.currency.code === "USD"
								? "."
								: `, converted at 1 USD = ${report.currency.usdRate} ${report.currency.code}.`}{" "}
							Calls on models without a catalog price count their tokens but
							not their cost.
							{report.trackingStartedAt &&
								` Usage has been recorded live since ${parseIsoDate(report.trackingStartedAt).toLocaleDateString(undefined, { dateStyle: "medium" })}; earlier usage was rebuilt from conversation history.`}
						</p>
					</>
				)}
			</div>

			<UsageSettingsDialog
				open={settingsOpen}
				onOpenChange={setSettingsOpen}
				onSaved={() => {
					invalidateSummaries();
					setReloadKey((key) => key + 1);
				}}
			/>
		</WorkspacePage>
	);
}

/** All-time view: no previous period, so rank the biggest consumers instead. */
function TopSpenders({
	report,
	currency,
	onSelect,
}: {
	report: UsageReport;
	currency: string;
	onSelect: (dimension: FilterDimension, key: string) => void;
}) {
	const rows = (["agent", "trigger", "project"] as const)
		.flatMap((dimension) =>
			(report.breakdowns[dimension] ?? [])
				.filter((row) => row.key && row.cost > 0)
				.map((row) => ({ dimension, row })),
		)
		.sort((a, b) => b.row.cost - a.row.cost)
		.slice(0, 5);

	return (
		<section className={cn(PANEL, "p-5")}>
			<h2 className="text-[15px] font-bold text-foreground">Top consumers</h2>
			<p className="mt-0.5 text-[12.5px] text-meta dark:text-panel-dim">
				Agents, triggers and projects with the highest spend.
			</p>
			<ul className="mt-3 space-y-1">
				{rows.map(({ dimension, row }) => (
					<li key={`${dimension}-${row.key}`}>
						<button
							type="button"
							className="flex w-full cursor-pointer items-center gap-3 rounded-[8px] px-2 py-2 text-left transition-colors hover:bg-[#F7FAF8] dark:hover:bg-white/[0.04]"
							onClick={() => {
								onSelect(dimension, row.key as string);
							}}
						>
							<div className="min-w-0 flex-1">
								<div className="truncate text-[13px] font-semibold text-foreground">{row.label}</div>
								<div className="text-[11.5px] text-meta">
									{DIMENSION_LABELS[dimension].singular} / {Math.round(row.share * 100)}% of spend
								</div>
							</div>
							<span className="shrink-0 font-mono text-[13px] font-semibold tabular-nums text-foreground">
								{formatMoney(row.cost, currency)}
							</span>
						</button>
					</li>
				))}
				{rows.length === 0 && (
					<li className="py-8 text-center text-[12.5px] text-meta">No spend recorded yet.</li>
				)}
			</ul>
		</section>
	);
}

function UsageSkeleton() {
	return (
		<div className="space-y-4" aria-busy="true">
			<div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
				{[0, 1, 2, 3].map((index) => (
					<div key={index} className={cn(PANEL, "h-[132px] animate-pulse")} />
				))}
			</div>
			<div className={cn(PANEL, "h-[340px] animate-pulse")} />
			<div className={cn(PANEL, "h-[280px] animate-pulse")} />
		</div>
	);
}

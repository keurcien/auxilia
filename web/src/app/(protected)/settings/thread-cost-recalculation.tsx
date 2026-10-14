"use client";

import { useEffect, useState } from "react";
import { Calendar, Check } from "lucide-react";
import { formatPillCost } from "@/components/layout/chat-header";
import {
	cancelCostBackfill,
	countBackfillThreads,
	getCostBackfill,
	startCostBackfill,
	type BackfillRange,
	type CostBackfill,
} from "@/lib/api/resources/thread-costs";
import { isApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

type Preset = "7d" | "month" | "lastmonth" | "all";

const PRESETS: { key: Preset; label: string }[] = [
	{ key: "7d", label: "Last 7 days" },
	{ key: "month", label: "This month" },
	{ key: "lastmonth", label: "Last month" },
	{ key: "all", label: "All time" },
];

/** `YYYY-MM-DD` in local time — the value a date input holds. */
function isoDay(date: Date): string {
	const pad = (n: number) => String(n).padStart(2, "0");
	return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * Inclusive local day bounds for a preset. "All time" spans the first thread's
 * day to today; until that day is known it stays blank (unbounded).
 */
export function presetRange(
	preset: Preset,
	today: Date,
	firstDay: string | null = null,
): { from: string; to: string } {
	const y = today.getFullYear();
	const m = today.getMonth();
	switch (preset) {
		case "7d":
			return { from: isoDay(new Date(y, m, today.getDate() - 6)), to: isoDay(today) };
		case "month":
			return { from: isoDay(new Date(y, m, 1)), to: isoDay(today) };
		case "lastmonth":
			return { from: isoDay(new Date(y, m - 1, 1)), to: isoDay(new Date(y, m, 0)) };
		case "all":
			return firstDay ? { from: firstDay, to: isoDay(today) } : { from: "", to: "" };
	}
}

/** The backend takes [startAt, endAt); the inputs are inclusive local days. */
export function toBackfillRange(from: string, to: string): BackfillRange {
	const midnight = (day: string, addDays = 0) => {
		const [y, m, d] = day.split("-").map(Number);
		return new Date(y, m - 1, d + addDays).toISOString();
	};
	return {
		startAt: from ? midnight(from) : null,
		endAt: to ? midnight(to, 1) : null,
	};
}

function timeAgo(iso: string): string {
	const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
	if (minutes < 1) return "just now";
	const format = new Intl.RelativeTimeFormat("en", { numeric: "auto" });
	if (minutes < 60) return format.format(-minutes, "minute");
	const hours = Math.round(minutes / 60);
	if (hours < 24) return format.format(-hours, "hour");
	return format.format(-Math.round(hours / 24), "day");
}

function plural(n: number, word: string): string {
	return `${n} ${word}${n === 1 ? "" : "s"}`;
}

function Result({ job }: { job: CostBackfill }) {
	const previous = Number(job.previousCost);
	const next = Number(job.newCost);
	const diff = next - previous;
	return (
		<div className="flex flex-col gap-3" aria-live="polite">
			<div className="flex items-center gap-2.5">
				<span className="flex size-[18px] flex-none items-center justify-center rounded-full bg-petrol">
					<Check className="size-2.5 text-white" strokeWidth={3} />
				</span>
				<span className="flex-1 text-[13.5px] font-bold text-foreground">
					{job.status === "cancelled"
						? `Cancelled after ${plural(job.processed, "thread")}`
						: `${plural(job.processed, "thread")} recalculated`}
				</span>
				{job.finishedAt && (
					<span className="font-mono text-[11px] text-meta">{timeAgo(job.finishedAt)}</span>
				)}
			</div>
			<div className="flex items-baseline gap-2.5 rounded-[9px] bg-petrol-tint/50 px-3 py-2.5 font-mono text-[13px] dark:bg-white/5">
				<span className="font-sans text-[12.5px] text-subtle">Total cost</span>
				{/* Only threads with an earlier estimate have a "before". */}
				{previous > 0 && (
					<span className="text-meta line-through">{formatPillCost(job.previousCost)}</span>
				)}
				<span className="font-semibold text-foreground">
					{previous > 0 && "→ "}
					{formatPillCost(job.newCost)}
				</span>
				{previous > 0 && diff !== 0 && (
					<span className={cn("text-[11.5px]", diff < 0 ? "text-success" : "text-warning")}>
						{diff < 0 ? "−" : "+"}
						{formatPillCost(String(Math.abs(diff)))}
					</span>
				)}
			</div>
			<div className="flex flex-wrap gap-1.5 text-[12px]">
				<span className="rounded-full bg-petrol-tint px-[9px] py-1 font-semibold text-petrol">
					{job.processed} updated
				</span>
				<span
					className={cn(
						"rounded-full px-[9px] py-1",
						job.incomplete > 0
							? "bg-warning-bg font-semibold text-warning"
							: "bg-neutral-bg text-meta",
					)}
				>
					{job.incomplete} incomplete
				</span>
				<span className="rounded-full bg-neutral-bg px-[9px] py-1 text-meta">
					{job.skipped} skipped
				</span>
				<span className="rounded-full bg-neutral-bg px-[9px] py-1 text-meta">
					{job.failed} failed
				</span>
			</div>
			{job.unpricedModels.length > 0 && (
				<Note>
					{plural(job.incomplete, "thread")} used a model with no price set (
					{job.unpricedModels.map((id, i) => (
						<span key={id}>
							{i > 0 && ", "}
							<code className="font-mono text-[11px]">{id}</code>
						</span>
					))}
					), so {job.incomplete === 1 ? "it's" : "they're"} only partially counted.
				</Note>
			)}
			{job.incomplete > 0 && job.unpricedModels.length === 0 && (
				<Note>
					{plural(job.incomplete, "thread")} {job.incomplete === 1 ? "has" : "have"} calls with
					no usage reported by the provider, so {job.incomplete === 1 ? "it's" : "they're"} only
					partially counted.
				</Note>
			)}
			{job.skipped > 0 && (
				<Note>Busy threads were skipped; run again after their runs finish.</Note>
			)}
			{job.lastError && <Note>Last failure: {job.lastError}</Note>}
		</div>
	);
}

function Note({ children }: { children: React.ReactNode }) {
	return (
		<p className="m-0 flex items-start gap-2 text-[12px] leading-[1.5] text-subtle">
			<span className="mt-1.5 size-1.5 flex-none rounded-full bg-warning" aria-hidden />
			<span>{children}</span>
		</p>
	);
}

export default function ThreadCostRecalculation() {
	const [preset, setPreset] = useState<Preset | null>("month");
	const [{ from, to }, setRange] = useState(() => presetRange("month", new Date()));
	const [count, setCount] = useState<number | null>(null);
	const [firstDay, setFirstDay] = useState<string | null>(null);
	const [job, setJob] = useState<CostBackfill | null>(null);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const active = job?.status === "pending" || job?.status === "running";
	const reversed = !!from && !!to && from > to;
	const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;

	useEffect(() => {
		let cancelled = false;
		getCostBackfill().then(
			(result) => {
				if (!cancelled) setJob(result);
			},
			(reason: unknown) => {
				if (!cancelled)
					setError(isApiError(reason) ? reason.detail : "Could not load recalculation status.");
			},
		);
		return () => {
			cancelled = true;
		};
	}, []);

	useEffect(() => {
		if (reversed) {
			setCount(null);
			return;
		}
		let cancelled = false;
		countBackfillThreads(toBackfillRange(from, to)).then(
			({ threads }) => {
				if (!cancelled) setCount(threads);
			},
			() => {
				if (!cancelled) setCount(null);
			},
		);
		return () => {
			cancelled = true;
		};
	}, [from, to, reversed]);

	// The first thread's day, for "All time" — one unranged count on mount.
	useEffect(() => {
		let cancelled = false;
		countBackfillThreads({ startAt: null, endAt: null }).then(
			({ firstCreatedAt }) => {
				if (!cancelled && firstCreatedAt) setFirstDay(isoDay(new Date(firstCreatedAt)));
			},
			() => {},
		);
		return () => {
			cancelled = true;
		};
	}, []);

	// "All time" picked before the first day arrived: fill the dates in now.
	useEffect(() => {
		if (firstDay && preset === "all" && !from) {
			setRange(presetRange("all", new Date(), firstDay));
		}
	}, [firstDay, preset, from]);

	// Poll while the worker runs; each response schedules the next read.
	useEffect(() => {
		if (!active) return;
		let cancelled = false;
		const timer = setTimeout(() => {
			getCostBackfill().then(
				(result) => {
					if (!cancelled) {
						setJob(result);
						setError(null);
					}
				},
				(reason: unknown) => {
					if (!cancelled)
						setError(isApiError(reason) ? reason.detail : "Could not load progress. Refresh to try again.");
				},
			);
		}, 2000);
		return () => {
			cancelled = true;
			clearTimeout(timer);
		};
	}, [active, job]);

	async function start() {
		setBusy(true);
		setError(null);
		try {
			setJob(await startCostBackfill(toBackfillRange(from, to)));
		} catch (reason: unknown) {
			setError(isApiError(reason) ? reason.detail : "Could not start the recalculation.");
		} finally {
			setBusy(false);
		}
	}

	async function cancel() {
		setBusy(true);
		try {
			setJob(await cancelCostBackfill());
			setError(null);
		} catch (reason: unknown) {
			setError(isApiError(reason) ? reason.detail : "Could not cancel the recalculation.");
		} finally {
			setBusy(false);
		}
	}

	const done = job ? job.processed + job.skipped + job.failed : 0;
	const finished = job && (job.status === "complete" || job.status === "cancelled");
	const dateInputClass =
		"border-none bg-transparent p-0 text-[13px] text-foreground outline-none disabled:opacity-60 dark:[color-scheme:dark]";

	return (
		<section
			aria-labelledby="recalc-title"
			className="flex max-w-[560px] flex-col gap-4 rounded-xl border border-border p-5"
		>
			<div className="flex flex-col gap-1">
				<h3 id="recalc-title" className="m-0 text-[14.5px] font-bold text-foreground">
					Recalculate thread costs
				</h3>
				<p className="m-0 text-[12.5px] leading-[1.5] text-subtle [text-wrap:pretty]">
					Replace saved estimates with current model prices. Use it after a price change.
				</p>
			</div>

			{active ? (
				<div className="flex flex-col gap-2.5" aria-live="polite">
					<div className="flex items-center gap-2.5">
						<span
							className="size-4 flex-none animate-spin rounded-full border-2 border-petrol-tint border-t-petrol"
							aria-hidden
						/>
						<span className="flex-1 text-[13px] font-semibold text-foreground">Recalculating…</span>
						<span className="font-mono text-[11px] text-meta">
							{done} / {job.total}
						</span>
						<button
							type="button"
							onClick={() => {
								void cancel();
							}}
							disabled={busy}
							className="cursor-pointer rounded-md px-2 py-1 text-[12px] font-semibold text-subtle transition-colors hover:bg-neutral-bg hover:text-foreground disabled:cursor-default disabled:opacity-60"
						>
							Cancel
						</button>
					</div>
					<div
						role="progressbar"
						aria-valuemin={0}
						aria-valuemax={job.total}
						aria-valuenow={done}
						className="h-1 overflow-hidden rounded-sm bg-border"
					>
						<div
							className="h-full bg-petrol transition-[width] duration-300"
							style={{ width: `${job.total ? (done / job.total) * 100 : 0}%` }}
						/>
					</div>
				</div>
			) : (
				<>
					<div className="flex flex-col gap-2">
						<span className="text-[12.5px] font-semibold text-foreground">Threads created</span>
						<div className="flex flex-wrap gap-1.5" role="group" aria-label="Date presets">
							{PRESETS.map(({ key, label }) => (
								<button
									key={key}
									type="button"
									aria-pressed={preset === key}
									onClick={() => {
										setPreset(key);
										setRange(presetRange(key, new Date(), firstDay));
									}}
									className={cn(
										"cursor-pointer rounded-full px-2.5 py-[5px] text-[12px] transition-colors",
										preset === key
											? "bg-foreground font-semibold text-background"
											: "bg-neutral-bg text-subtle hover:bg-hover",
									)}
								>
									{label}
								</button>
							))}
						</div>
						<div className="flex flex-wrap items-center gap-2.5 rounded-[9px] border border-input px-3 py-[9px] focus-within:border-petrol focus-within:ring-[3px] focus-within:ring-petrol-tint">
							<Calendar className="size-3.5 text-subtle" aria-hidden />
							<input
								type="date"
								aria-label="Created on or after"
								value={from}
								max={to || undefined}
								onChange={(event) => {
									setPreset(null);
									setRange({ from: event.target.value, to });
								}}
								className={dateInputClass}
							/>
							<span className="text-[13px] text-meta">→</span>
							<input
								type="date"
								aria-label="Created on or before"
								value={to}
								min={from || undefined}
								onChange={(event) => {
									setPreset(null);
									setRange({ from, to: event.target.value });
								}}
								className={dateInputClass}
							/>
							<span className="ml-auto font-mono text-[10.5px] text-meta">{timeZone}</span>
						</div>
					</div>

					<div className="flex items-center gap-3 pt-1">
						<span className="flex-1 text-[12.5px] text-subtle">
							{reversed ? (
								"The start date is after the end date."
							) : count === null ? (
								"Counting threads…"
							) : (
								<>
									<b className="text-foreground">{plural(count, "thread")}</b> will be recalculated
								</>
							)}
						</span>
						<button
							type="button"
							onClick={() => {
								void start();
							}}
							disabled={busy || reversed || !count}
							className="cursor-pointer rounded-lg bg-petrol px-3.5 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-default disabled:bg-border disabled:text-meta disabled:opacity-100"
						>
							Recalculate {count ? plural(count, "thread") : "threads"}
						</button>
					</div>
				</>
			)}

			{finished && !active && <Result job={job} />}
			{error && (
				<p role="alert" className="m-0 text-[12.5px] text-destructive">
					{error}
				</p>
			)}
		</section>
	);
}

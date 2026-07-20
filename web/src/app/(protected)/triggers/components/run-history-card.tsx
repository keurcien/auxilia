"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { formatRunAt } from "@/lib/triggers/schedule";
import { TriggerThread } from "@/types/triggers";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";
import { useActiveRunThreadIdSet } from "@/hooks/use-active-runs";

interface RunHistoryCardProps {
	triggerId: string;
	timezone: string;
}

/** Trigger runs execute as the trigger's *owner*, so the viewer's
 * `/runs/active` poll can't see firings of someone else's trigger (e.g. an
 * admin watching it). While the card is open, refresh the history itself —
 * new firings and outcomes then surface regardless of who owns the run. */
const HISTORY_POLL_MS = 15_000;

/** A firing whose run outcome is missing is in flight — every firing
 * enqueues a run, and terminal transitions always stamp the thread. Bound
 * it in time so the rare orphan (enqueue crashed after the thread was
 * committed) doesn't spin forever; the reaper finalizes real runs long
 * before this. */
const MISSING_OUTCOME_RUNNING_WINDOW_MS = 24 * 60 * 60 * 1000;

function isInFlight(run: TriggerThread): boolean {
	return (
		!run.lastRunStatus &&
		Date.now() - new Date(run.createdAt).getTime() <
			MISSING_OUTCOME_RUNNING_WINDOW_MS
	);
}

/** Past firings (last 30 days); each row opens the thread it created. */
export default function RunHistoryCard({
	triggerId,
	timezone,
}: RunHistoryCardProps) {
	const runs = useTriggerRunsStore((state) => state.runsByTrigger[triggerId]);
	const fetchRuns = useTriggerRunsStore((state) => state.fetchRuns);
	const activeRunThreadIds = useActiveRunThreadIdSet();

	useEffect(() => {
		fetchRuns(triggerId).catch(() => {
			// logged by the store; the card keeps whatever it has
		});
		const timer = setInterval(() => {
			if (document.visibilityState === "hidden") return;
			fetchRuns(triggerId).catch(() => {
				// logged by the store; the card keeps whatever it has
			});
		}, HISTORY_POLL_MS);
		return () => {
			clearInterval(timer);
		};
	}, [triggerId, fetchRuns]);

	// A scheduled firing while the card is open surfaces as an active thread
	// id the fetched history doesn't have yet — refetch so its row appears.
	// Active ids that belong to other threads (e.g. a chat run) can never
	// show up in this trigger's history, so remember the ids already looked
	// up and refetch at most once per unknown id.
	const checkedThreadIdsRef = useRef(new Set<string>());
	useEffect(() => {
		if (runs === undefined) return;
		const known = new Set(runs.map((run) => run.id));
		let hasUnknown = false;
		for (const threadId of activeRunThreadIds) {
			if (known.has(threadId) || checkedThreadIdsRef.current.has(threadId)) {
				continue;
			}
			checkedThreadIdsRef.current.add(threadId);
			hasUnknown = true;
		}
		if (!hasUnknown) return;
		fetchRuns(triggerId).catch(() => {
			// logged by the store; the card keeps whatever it has
		});
	}, [runs, activeRunThreadIds, triggerId, fetchRuns]);

	return (
		<div className="flex flex-col rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card px-4.5 py-1.5 shadow-[0_1px_3px_rgba(33,36,31,0.04)]">
			{runs === undefined && (
				<p className="py-3.5 font-[family-name:var(--font-dm-sans)] text-[13px] text-[#A3B5AD] dark:text-muted-foreground">
					Loading…
				</p>
			)}
			{runs !== undefined && runs.length === 0 && (
				<p className="py-3.5 font-[family-name:var(--font-dm-sans)] text-[13px] text-[#A3B5AD] dark:text-muted-foreground">
					No runs yet.
				</p>
			)}
			{runs?.map((run) => (
				<Link
					key={run.id}
					href={`/agents/${run.agentId}/chat/${run.id}`}
					className="group flex items-center gap-3 py-3.5 border-b border-[#F1F5F3] dark:border-white/5 last:border-b-0"
				>
					<span className="flex-1 min-w-0 truncate font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-white group-hover:text-[#3D8B63] dark:group-hover:text-emerald-400 transition-colors">
						{formatRunAt(run.createdAt, timezone)}
					</span>
					{activeRunThreadIds.has(run.id) || isInFlight(run) ? (
						<span className="flex shrink-0 items-center gap-1">
							<Loader2
								aria-hidden="true"
								className="size-[13px] shrink-0 animate-spin text-[#4CA882]"
							/>
							<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px]/4 font-semibold text-[#4CA882]">
								Running
							</span>
						</span>
					) : (
						(run.lastRunStatus === "error" ||
							run.lastRunStatus === "timeout") && (
							<span className="flex shrink-0 items-center gap-1">
								<svg
									width="13"
									height="13"
									viewBox="0 0 24 24"
									xmlns="http://www.w3.org/2000/svg"
									className="shrink-0"
									aria-hidden="true"
								>
									<path
										d="M18 6L6 18M6 6l12 12"
										fill="none"
										stroke="#CE5B45"
										strokeWidth="3"
										strokeLinecap="round"
										strokeLinejoin="round"
									/>
								</svg>
								<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px]/4 font-semibold text-[#CE5B45]">
									Failed
								</span>
							</span>
						)
					)}
				</Link>
			))}
		</div>
	);
}

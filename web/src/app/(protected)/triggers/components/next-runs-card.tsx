"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { formatRunAt } from "@/lib/triggers/schedule";
import { SchedulePreview } from "@/types/triggers";

interface NextRunsCardProps {
	/** null = nothing to preview yet (incomplete schedule). */
	cronExpression: string | null;
	timezone: string;
	/** Render the rows without the card chrome (for embedding in a card). */
	bare?: boolean;
	className?: string;
}

/**
 * Upcoming firings for a cron/timezone pair, computed by the backend
 * preview endpoint — the ground truth for whatever the builder produced.
 * A 400 here doubles as pre-save schedule validation.
 */
export default function NextRunsCard({
	cronExpression,
	timezone,
	bare,
	className,
}: NextRunsCardProps) {
	const [runs, setRuns] = useState<string[]>([]);
	const [error, setError] = useState<string | null>(null);
	const requestSeqRef = useRef(0);

	useEffect(() => {
		const seq = ++requestSeqRef.current;
		const timer = setTimeout(
			() => {
				if (!cronExpression) {
					if (requestSeqRef.current === seq) {
						setRuns([]);
						setError(null);
					}
					return;
				}
				api
					.get<SchedulePreview>("/triggers/schedule/preview", {
						params: { cronExpression, timezone, count: 3 },
					})
					.then((response) => {
						if (requestSeqRef.current !== seq) return;
						setRuns(response.data.nextRunAts);
						setError(null);
					})
					.catch((err: unknown) => {
						if (requestSeqRef.current !== seq) return;
						setRuns([]);
						setError(
							getApiErrorMessage(err, "This schedule can't be computed."),
						);
					});
			},
			cronExpression ? 400 : 0,
		);
		return () => {
			clearTimeout(timer);
		};
	}, [cronExpression, timezone]);

	return (
		<div
			className={cn(
				"flex flex-col",
				!bare &&
					"rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card px-4.5 py-1.5 shadow-[0_1px_3px_rgba(33,36,31,0.04)]",
				className,
			)}
		>
			{!cronExpression && (
				<p className="py-3.5 font-[family-name:var(--font-dm-sans)] text-[13px] text-[#A3B5AD] dark:text-muted-foreground">
					Pick a schedule to preview upcoming runs.
				</p>
			)}
			{cronExpression && error && (
				<p className="py-3.5 font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#D45B45]">
					{error}
				</p>
			)}
			{cronExpression &&
				!error &&
				runs.map((iso, index) => (
					<div
						key={iso}
						className="flex items-center gap-3 py-3 border-b border-[#F1F5F3] dark:border-white/5 last:border-b-0"
					>
						<span
							className={cn(
								"flex items-center justify-center size-[30px] shrink-0 rounded-full",
								index === 0
									? "bg-[#EDF4F0] dark:bg-emerald-950/40"
									: "bg-[#F3F6F4] dark:bg-white/5",
							)}
						>
							<span
								className={cn(
									"size-[7px] rounded-full",
									index === 0 ? "bg-[#4CA882]" : "bg-[#C2CFC8]",
								)}
							/>
						</span>
						<span
							className={cn(
								"font-[family-name:var(--font-dm-sans)] text-[14px]",
								index === 0
									? "font-semibold text-[#1E2D28] dark:text-white"
									: "font-medium text-[#3A4A43] dark:text-white/70",
							)}
						>
							{formatRunAt(iso, timezone)}
						</span>
					</div>
				))}
		</div>
	);
}

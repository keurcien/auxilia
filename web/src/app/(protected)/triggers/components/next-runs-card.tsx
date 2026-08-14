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
				!bare && "rounded-[10px] border border-border bg-card px-4.5 py-1.5",
				className,
			)}
		>
			{!cronExpression && (
				<p className="py-3.5 text-[13px] text-faint dark:text-muted-foreground">
					Pick a schedule to preview upcoming runs.
				</p>
			)}
			{cronExpression && error && (
				<p className="py-3.5 text-[13px] font-medium text-destructive">
					{error}
				</p>
			)}
			{cronExpression &&
				!error &&
				runs.map((iso, index) => (
					<div
						key={iso}
						className="flex items-center gap-3 py-3 border-b border-hairline dark:border-white/5 last:border-b-0"
					>
						<span
							className={cn(
								"flex items-center justify-center size-[30px] shrink-0 rounded-full",
								index === 0
									? "bg-petrol-tint dark:bg-white/10"
									: "bg-hover dark:bg-white/5",
							)}
						>
							<span
								className={cn(
									"size-[7px] rounded-full",
									index === 0 ? "bg-petrol" : "bg-faint",
								)}
							/>
						</span>
						<span
							className={cn(
								"text-[14px]",
								index === 0
									? "font-semibold text-foreground"
									: "font-medium text-body dark:text-white/70",
							)}
						>
							{formatRunAt(iso, timezone)}
						</span>
					</div>
				))}
		</div>
	);
}

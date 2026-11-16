"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

/** `YYYY-MM-DD` of a local date. */
function toIso(date: Date): string {
	const month = String(date.getMonth() + 1).padStart(2, "0");
	const day = String(date.getDate()).padStart(2, "0");
	return `${date.getFullYear()}-${month}-${day}`;
}

function addMonths(month: Date, count: number): Date {
	return new Date(month.getFullYear(), month.getMonth() + count, 1);
}

// 2024-01-01 is a Monday; weeks start on Monday, like the usage buckets.
const WEEKDAYS = Array.from({ length: 7 }, (_, index) =>
	new Date(2024, 0, 1 + index).toLocaleDateString(undefined, { weekday: "narrow" }),
);

interface RangeCalendarProps {
	start: string | null;
	end: string | null;
	onSelect: (day: string) => void;
	/** Right-most visible month (any day of it). */
	month: Date;
	onMonthChange: (month: Date) => void;
	/** Last selectable day, inclusive. */
	max?: string;
	months?: number;
}

export function RangeCalendar({
	start,
	end,
	onSelect,
	month,
	onMonthChange,
	max,
	months = 2,
}: RangeCalendarProps) {
	const [hovered, setHovered] = useState<string | null>(null);
	const last = new Date(month.getFullYear(), month.getMonth(), 1);
	const visible = Array.from({ length: months }, (_, index) =>
		addMonths(last, index - months + 1),
	);
	const atMax = max !== undefined && toIso(addMonths(last, 1)) > max;
	const today = toIso(new Date());

	// While only the start is picked, the hovered day previews the range.
	const other = end ?? (start && hovered ? hovered : null);
	const [low, high] =
		start && other ? (start <= other ? [start, other] : [other, start]) : [start, start];

	return (
		<div className="relative flex gap-6" onMouseLeave={() => { setHovered(null); }}>
			<button
				type="button"
				aria-label="Previous month"
				className="absolute top-0 left-0 flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover hover:text-foreground dark:hover:bg-white/10"
				onClick={() => {
					onMonthChange(addMonths(last, -1));
				}}
			>
				<ChevronLeft className="size-4" />
			</button>
			<button
				type="button"
				aria-label="Next month"
				disabled={atMax}
				className="absolute top-0 right-0 flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover hover:text-foreground disabled:cursor-default disabled:opacity-30 disabled:hover:bg-transparent dark:hover:bg-white/10"
				onClick={() => {
					onMonthChange(addMonths(last, 1));
				}}
			>
				<ChevronRight className="size-4" />
			</button>
			{visible.map((first) => {
				const offset = (first.getDay() + 6) % 7;
				const length = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
				return (
					<div key={toIso(first)} className="w-[224px]">
						<div className="flex h-7 items-center justify-center text-[13px] font-semibold text-foreground">
							{first.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
						</div>
						<div className="mt-2 grid grid-cols-7 text-center text-[11px] font-medium text-meta dark:text-panel-dim">
							{WEEKDAYS.map((weekday, index) => (
								<span key={index} className="py-1">
									{weekday}
								</span>
							))}
						</div>
						<div className="grid grid-cols-7 gap-y-0.5">
							{Array.from({ length: 42 }, (_, index) => {
								const dayOfMonth = index - offset + 1;
								if (dayOfMonth < 1 || dayOfMonth > length) {
									return <div key={index} className="h-8" />;
								}
								const day = toIso(new Date(first.getFullYear(), first.getMonth(), dayOfMonth));
								const disabled = max !== undefined && day > max;
								const inRange = low !== null && high !== null && day >= low && day <= high;
								const endpoint = day === low || day === high;
								const column = index % 7;
								return (
									<div
										key={index}
										className={cn(
											"flex h-8 items-center justify-center",
											inRange && "bg-petrol-tint dark:bg-white/10",
											inRange &&
												(day === low || column === 0 || dayOfMonth === 1) &&
												"rounded-l-[8px]",
											inRange &&
												(day === high || column === 6 || dayOfMonth === length) &&
												"rounded-r-[8px]",
										)}
									>
										<button
											type="button"
											disabled={disabled}
											aria-pressed={endpoint}
											aria-label={new Date(
												first.getFullYear(),
												first.getMonth(),
												dayOfMonth,
											).toLocaleDateString(undefined, { dateStyle: "full" })}
											className={cn(
												"size-8 cursor-pointer rounded-[8px] text-[12.5px] tabular-nums transition-colors",
												endpoint
													? "bg-petrol font-semibold text-white dark:bg-panel-terminal dark:text-card"
													: inRange
														? "text-petrol hover:bg-petrol/10 dark:text-panel-terminal"
														: "text-foreground hover:bg-hover dark:hover:bg-white/10",
												day === today && !endpoint && "font-bold underline underline-offset-4",
												disabled &&
													"cursor-default text-meta/40 hover:bg-transparent dark:text-panel-dim/40 dark:hover:bg-transparent",
											)}
											onMouseEnter={() => {
												setHovered(day);
											}}
											onClick={() => {
												onSelect(day);
											}}
										>
											{dayOfMonth}
										</button>
									</div>
								);
							})}
						</div>
					</div>
				);
			})}
		</div>
	);
}

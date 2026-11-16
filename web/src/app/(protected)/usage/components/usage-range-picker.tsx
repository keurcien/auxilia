"use client";

import { useState } from "react";
import { CalendarRange, Check, ChevronDown } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RangeCalendar } from "@/components/ui/range-calendar";
import { useIsMobile } from "@/hooks/use-mobile";
import { formatRange, isoDate, parseIsoDate } from "@/lib/usage/format";
import { cn } from "@/lib/utils";
import { RANGE_PRESETS, rangeDates, rangeDays, rangeLabel, type UsageRange } from "../range";

interface Draft {
	start: string | null;
	end: string | null;
}

export function UsageRangePicker({
	range,
	resolved,
	onChange,
}: {
	range: UsageRange;
	/** Dates the current report covers, so "All time" opens on its real start. */
	resolved?: { start: string; end: string };
	onChange: (range: UsageRange) => void;
}) {
	const isMobile = useIsMobile();
	const [open, setOpen] = useState(false);
	const [draft, setDraft] = useState<Draft>({ start: null, end: null });
	const [month, setMonth] = useState(() => new Date());
	const today = isoDate(new Date());

	const openPicker = () => {
		const dates = range.preset === "custom" ? range : (resolved ?? rangeDates(range));
		const start = dates.start ?? null;
		const end = dates.end ?? null;
		setDraft({ start, end });
		setMonth(end ? parseIsoDate(end) : new Date());
	};

	const pick = (day: string) => {
		setDraft((current) => {
			if (!current.start || current.end) return { start: day, end: null };
			return day < current.start
				? { start: day, end: current.start }
				: { start: current.start, end: day };
		});
	};

	const apply = (next: UsageRange) => {
		onChange(next);
		setOpen(false);
	};

	const summary =
		draft.start && draft.end
			? `${formatRange(draft.start, draft.end)} / ${rangeDays(draft.start, draft.end)} ${rangeDays(draft.start, draft.end) === 1 ? "day" : "days"}`
			: draft.start
				? "Pick an end date"
				: "Pick a start date";

	return (
		<Popover
			open={open}
			onOpenChange={(next) => {
				if (next) openPicker();
				setOpen(next);
			}}
		>
			<PopoverTrigger asChild>
				<button
					type="button"
					className="flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-[8px] border border-input px-3 py-[7px] text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover data-[state=open]:border-border-hover dark:border-white/10"
				>
					<CalendarRange className="size-3.5 text-meta" />
					{rangeLabel(range)}
					<ChevronDown className="size-3.5 text-meta" />
				</button>
			</PopoverTrigger>
			<PopoverContent className="flex max-w-[calc(100vw-24px)] flex-col md:flex-row">
				<div className="flex flex-wrap gap-1 border-b border-hairline p-2 md:w-[150px] md:shrink-0 md:flex-col md:flex-nowrap md:border-r md:border-b-0 dark:border-white/10">
					{RANGE_PRESETS.map((option) => {
						const active = option.key === range.preset;
						return (
							<button
								key={option.key}
								type="button"
								className={cn(
									"flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-[6px] px-2.5 py-1.5 text-left text-[13px] font-medium text-ink transition-colors hover:bg-hover dark:text-panel-button dark:hover:bg-white/5",
									active && "bg-petrol-tint dark:bg-white/10",
								)}
								onClick={() => {
									apply({ preset: option.key });
								}}
							>
								<span className="flex-1">{option.label}</span>
								{active && (
									<Check
										className="hidden size-3.5 text-petrol md:block dark:text-panel-terminal"
										strokeWidth={3}
									/>
								)}
							</button>
						);
					})}
				</div>
				<div className="p-3">
					<RangeCalendar
						start={draft.start}
						end={draft.end}
						onSelect={pick}
						month={month}
						onMonthChange={setMonth}
						max={today}
						months={isMobile ? 1 : 2}
					/>
					<div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-hairline pt-3 dark:border-white/10">
						<span className="text-[12.5px] tabular-nums text-meta dark:text-panel-dim">
							{summary}
						</span>
						<div className="flex items-center gap-2">
							<button
								type="button"
								className="cursor-pointer rounded-[7px] px-3 py-1.5 text-[13px] font-semibold text-meta transition-colors hover:text-foreground"
								onClick={() => {
									setOpen(false);
								}}
							>
								Cancel
							</button>
							<button
								type="button"
								disabled={!draft.start || !draft.end}
								className="cursor-pointer rounded-[7px] bg-petrol px-3 py-1.5 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-40 dark:bg-panel-terminal dark:text-card"
								onClick={() => {
									if (draft.start && draft.end) {
										apply({ preset: "custom", start: draft.start, end: draft.end });
									}
								}}
							>
								Apply
							</button>
						</div>
					</div>
				</div>
			</PopoverContent>
		</Popover>
	);
}

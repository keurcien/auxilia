"use client";

import { useRef } from "react";
import { ChevronDown, Clock, Repeat } from "lucide-react";
import { cn } from "@/lib/utils";
import {
	describeSchedule,
	Schedule,
	Weekday,
	WEEKDAY_CHIP_LABELS,
	WEEKDAY_CHIP_ORDER,
} from "@/lib/triggers/schedule";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";

interface ScheduleBuilderProps {
	value: Schedule;
	onChange: (schedule: Schedule) => void;
	timezone: string;
	/** Render the rows without the card chrome (for embedding in a card). */
	bare?: boolean;
}

const PRESETS: { kind: Exclude<Schedule["kind"], "raw">; label: string }[] = [
	{ kind: "daily", label: "Every day" },
	{ kind: "weekdays", label: "Weekdays (Mon–Fri)" },
	{ kind: "weekly", label: "Once a week" },
	{ kind: "biweekly", label: "Every two weeks" },
	{ kind: "monthly", label: "Once a month" },
	{ kind: "custom", label: "Custom…" },
];

function presetLabel(schedule: Schedule): string {
	if (schedule.kind === "raw") {
		return "Custom cron";
	}
	return PRESETS.find((preset) => preset.kind === schedule.kind)?.label ?? "";
}

function withKind(
	value: Schedule,
	kind: Exclude<Schedule["kind"], "raw">,
): Schedule {
	const time = value.kind === "raw" ? "09:00" : value.time;
	const day: Weekday =
		value.kind === "weekly" || value.kind === "biweekly" ? value.day : 1;
	switch (kind) {
		case "daily":
		case "weekdays":
		case "monthly":
			return { kind, time };
		case "weekly":
		case "biweekly":
			return { kind, day, time };
		case "custom":
			return { kind, interval: 1, unit: "week", days: [day], time };
	}
}

function DayChips({
	selected,
	onToggle,
}: {
	selected: Weekday[];
	onToggle: (day: Weekday) => void;
}) {
	return (
		<div className="flex gap-1.5">
			{WEEKDAY_CHIP_ORDER.map((day) => {
				const isSelected = selected.includes(day);
				return (
					<button
						key={day}
						type="button"
						onClick={() => {
							onToggle(day);
						}}
						className={cn(
							"flex-1 h-10 rounded-[11px] font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold cursor-pointer transition-colors",
							isSelected
								? "bg-[#1E2D28] text-white dark:bg-white dark:text-[#111111]"
								: "bg-white dark:bg-transparent text-[#5A6B63] dark:text-white/60 border border-[#E4EAE7] dark:border-white/10 hover:border-[#A3B5AD]",
						)}
					>
						{WEEKDAY_CHIP_LABELS[day]}
					</button>
				);
			})}
		</div>
	);
}

const fieldClassName =
	"flex items-center justify-between h-12 px-3.5 rounded-xl border border-[#E4EAE7] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-white cursor-pointer transition-colors hover:border-[#A3B5AD]";

export default function ScheduleBuilder({
	value,
	onChange,
	timezone,
	bare,
}: ScheduleBuilderProps) {
	const time = value.kind === "raw" ? null : value.time;
	const timeInputRef = useRef<HTMLInputElement>(null);

	const singleDay =
		value.kind === "weekly" || value.kind === "biweekly" ? value.day : null;

	const handleIntervalChange = (interval: number) => {
		if (value.kind !== "custom") return;
		const max = value.unit === "week" ? 2 : 30;
		onChange({
			...value,
			interval: Math.min(Math.max(1, Math.round(interval) || 1), max),
		});
	};

	return (
		<div
			className={cn(
				"flex flex-col gap-4",
				!bare &&
					"rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card p-5 shadow-[0_1px_3px_rgba(33,36,31,0.04)]",
			)}
		>
			{/* Preset · at · time */}
			<div className="flex items-center gap-3">
				<SageDropdownMenu
					align="start"
					className="min-w-[240px]"
					trigger={
						<button type="button" className={cn(fieldClassName, "flex-1")}>
							{presetLabel(value)}
							<ChevronDown className="size-[18px] shrink-0 text-[#9AA8A1]" />
						</button>
					}
					items={PRESETS.map((preset) => ({
						label: preset.label,
						active: value.kind === preset.kind,
						onClick: () => {
							onChange(withKind(value, preset.kind));
						},
					}))}
				/>
				{time !== null && (
					<>
						<span className="shrink-0 font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#7C8C84] dark:text-muted-foreground">
							at
						</span>
						<div className="flex items-center shrink-0 h-12 rounded-xl overflow-hidden border border-[#E4EAE7] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-white transition-colors">
							<label className="flex items-center gap-1.5 pl-3.5 pr-3 cursor-pointer">
								<Clock className="size-[15px] shrink-0 text-[#9AA8A1]" />
								<input
									ref={timeInputRef}
									type="time"
									value={time}
									onChange={(e) => {
										if (!e.target.value) return;
										onChange({ ...value, time: e.target.value } as Schedule);
									}}
									className="bg-transparent border-none outline-none font-semibold text-[#1E2D28] dark:text-white cursor-pointer appearance-none [&::-webkit-calendar-picker-indicator]:hidden"
								/>
							</label>
							<span className="w-px self-stretch shrink-0 bg-[#E4EAE7] dark:bg-white/10" />
							<button
								type="button"
								aria-label="Open time picker"
								onClick={() => {
									timeInputRef.current?.showPicker?.();
								}}
								className="flex items-center justify-center w-9.5 self-stretch shrink-0 bg-[#F6F9F7] dark:bg-white/5 text-[#7C8C84] dark:text-muted-foreground cursor-pointer hover:bg-[#EEF3F0] dark:hover:bg-white/10 transition-colors"
							>
								<ChevronDown className="size-4 shrink-0" />
							</button>
						</div>
					</>
				)}
			</div>

			{/* Single-day pick for weekly / biweekly */}
			{singleDay !== null && (
				<div className="flex flex-col gap-2.5">
					<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px] font-semibold text-[#7C8C84] dark:text-muted-foreground">
						On
					</span>
					<DayChips
						selected={[singleDay]}
						onToggle={(day) => {
							onChange({ ...value, day } as Schedule);
						}}
					/>
				</div>
			)}

			{/* Custom: repeat every N unit (+ day chips for weeks) */}
			{value.kind === "custom" && (
				<>
					<div className="h-px shrink-0 bg-[#EEF3F0] dark:bg-white/5" />
					<div className="flex items-center gap-2.5">
						<span className="shrink-0 font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#3A4A43] dark:text-white/80">
							Repeat every
						</span>
						<input
							type="number"
							min={1}
							max={value.unit === "week" ? 2 : 30}
							value={value.interval}
							onChange={(e) => {
								handleIntervalChange(Number(e.target.value));
							}}
							className="w-16 h-[42px] px-3 rounded-[11px] border border-[#E4EAE7] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-white outline-none focus:border-[#4CA882] transition-colors"
						/>
						<SageDropdownMenu
							align="start"
							trigger={
								<button
									type="button"
									className={cn(fieldClassName, "flex-1 h-[42px]")}
								>
									{value.unit === "day"
										? value.interval === 1
											? "day"
											: "days"
										: value.interval === 1
											? "week"
											: "weeks"}
									<ChevronDown className="size-[16px] shrink-0 text-[#9AA8A1]" />
								</button>
							}
							items={(["day", "week"] as const).map((unit) => ({
								label: unit === "day" ? "days" : "weeks",
								active: value.unit === unit,
								onClick: () => {
									onChange({
										...value,
										unit,
										// week intervals are only expressible up to 2
										interval:
											unit === "week"
												? Math.min(value.interval, 2)
												: value.interval,
									});
								},
							}))}
						/>
					</div>
					{value.unit === "week" && (
						<div className="flex flex-col gap-2.5">
							<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px] font-semibold text-[#7C8C84] dark:text-muted-foreground">
								On days
							</span>
							<DayChips
								selected={value.days}
								onToggle={(day) => {
									const days = value.days.includes(day)
										? value.days.filter((d) => d !== day)
										: [...value.days, day];
									onChange({ ...value, days });
								}}
							/>
						</div>
					)}
				</>
			)}

			{/* Raw cron fallback */}
			{value.kind === "raw" && (
				<div className="flex items-center justify-between gap-3 rounded-[10px] bg-[#F4F8F5] dark:bg-white/5 px-3.5 py-3">
					<code className="font-mono text-[13px] text-[#1E2D28] dark:text-white truncate">
						{value.cronExpression}
					</code>
					<button
						type="button"
						onClick={() => {
							onChange(withKind(value, "custom"));
						}}
						className="shrink-0 font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#3D8B63] dark:text-emerald-400 cursor-pointer hover:underline"
					>
						Edit as custom
					</button>
				</div>
			)}

			{/* Summary line — only when the schedule needs spelling out */}
			{value.kind === "custom" && (
				<div className="flex items-center gap-2.5 rounded-[10px] bg-[#F4F8F5] dark:bg-white/5 px-3.5 py-3">
					<Repeat className="size-[15px] shrink-0 text-[#5E8C76] dark:text-emerald-400" />
					<span className="font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#42594F] dark:text-white/70">
						{describeSchedule(value)} · {timezone}
					</span>
				</div>
			)}
		</div>
	);
}

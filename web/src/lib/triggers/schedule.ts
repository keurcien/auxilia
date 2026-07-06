/**
 * Pure schedule <-> cron mapping for triggers.
 *
 * The backend stores a standard 5-field cron expression (validated by
 * croniter) plus an IANA timezone. The UI edits a structured `Schedule`
 * and derives the cron at save/preview time. `parseCronExpression`
 * recognizes exactly the shapes `buildCronExpression` emits; anything
 * else round-trips untouched as `{ kind: "raw" }`.
 *
 * "Every two weeks" uses croniter's nth-weekday hash syntax (`1#1,1#3` =
 * 1st and 3rd Monday of the month), which is approximately biweekly —
 * the next-runs preview endpoint is the ground truth shown to users.
 */

export type Weekday = 0 | 1 | 2 | 3 | 4 | 5 | 6; // cron numbering: 0 = Sunday

export type Schedule =
	| { kind: "daily"; time: string }
	| { kind: "weekdays"; time: string }
	| { kind: "weekly"; day: Weekday; time: string }
	| { kind: "biweekly"; day: Weekday; time: string }
	| { kind: "monthly"; time: string }
	| {
			kind: "custom";
			interval: number;
			unit: "day" | "week";
			days: Weekday[];
			time: string;
	  }
	| { kind: "raw"; cronExpression: string };

export const DEFAULT_SCHEDULE: Schedule = { kind: "daily", time: "09:00" };

/** Chips render Monday-first. */
export const WEEKDAY_CHIP_ORDER: Weekday[] = [1, 2, 3, 4, 5, 6, 0];

export const WEEKDAY_NAMES: Record<Weekday, string> = {
	0: "Sunday",
	1: "Monday",
	2: "Tuesday",
	3: "Wednesday",
	4: "Thursday",
	5: "Friday",
	6: "Saturday",
};

export const WEEKDAY_SHORT_NAMES: Record<Weekday, string> = {
	0: "Sun",
	1: "Mon",
	2: "Tue",
	3: "Wed",
	4: "Thu",
	5: "Fri",
	6: "Sat",
};

export const WEEKDAY_CHIP_LABELS: Record<Weekday, string> = {
	0: "S",
	1: "M",
	2: "T",
	3: "W",
	4: "T",
	5: "F",
	6: "S",
};

function timeToParts(time: string): { minute: number; hour: number } | null {
	const match = /^(\d{1,2}):(\d{2})$/.exec(time);
	if (!match) {
		return null;
	}
	const hour = Number(match[1]);
	const minute = Number(match[2]);
	if (hour > 23 || minute > 59) {
		return null;
	}
	return { minute, hour };
}

function partsToTime(minute: number, hour: number): string {
	return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

function sortDays(days: Weekday[]): Weekday[] {
	return [...days].sort((a, b) => a - b);
}

function biweeklyField(days: Weekday[]): string {
	return sortDays(days)
		.map((day) => `${day}#1,${day}#3`)
		.join(",");
}

/**
 * Returns the cron expression for a schedule, or null when the schedule
 * is incomplete or not expressible in cron (e.g. weekly custom with no
 * days, or a week interval other than 1 or 2).
 */
export function buildCronExpression(schedule: Schedule): string | null {
	if (schedule.kind === "raw") {
		return schedule.cronExpression;
	}

	const parts = timeToParts(schedule.time);
	if (!parts) {
		return null;
	}
	const { minute, hour } = parts;
	const at = `${minute} ${hour}`;

	switch (schedule.kind) {
		case "daily":
			return `${at} * * *`;
		case "weekdays":
			return `${at} * * 1-5`;
		case "weekly":
			return `${at} * * ${schedule.day}`;
		case "biweekly":
			return `${at} * * ${biweeklyField([schedule.day])}`;
		case "monthly":
			return `${at} 1 * *`;
		case "custom": {
			if (!Number.isInteger(schedule.interval) || schedule.interval < 1) {
				return null;
			}
			if (schedule.unit === "day") {
				return schedule.interval === 1
					? `${at} * * *`
					: `${at} */${schedule.interval} * *`;
			}
			// unit === "week"
			if (schedule.days.length === 0) {
				return null;
			}
			if (schedule.interval === 1) {
				return `${at} * * ${sortDays(schedule.days).join(",")}`;
			}
			if (schedule.interval === 2) {
				return `${at} * * ${biweeklyField(schedule.days)}`;
			}
			return null;
		}
	}
}

function parseWeekday(field: string): Weekday | null {
	if (!/^[0-6]$/.test(field)) {
		return null;
	}
	return Number(field) as Weekday;
}

function parseDayList(field: string): Weekday[] | null {
	const days: Weekday[] = [];
	for (const part of field.split(",")) {
		const day = parseWeekday(part);
		if (day === null) {
			return null;
		}
		days.push(day);
	}
	return days;
}

/** Parses `d#1,d#3[,d#1,d#3…]` back into the list of hashed weekdays. */
function parseBiweeklyDayList(field: string): Weekday[] | null {
	const parts = field.split(",");
	if (parts.length === 0 || parts.length % 2 !== 0) {
		return null;
	}
	const days: Weekday[] = [];
	for (let i = 0; i < parts.length; i += 2) {
		const match = /^([0-6])#1$/.exec(parts[i]);
		if (!match || parts[i + 1] !== `${match[1]}#3`) {
			return null;
		}
		days.push(Number(match[1]) as Weekday);
	}
	return days;
}

/**
 * Reverse of `buildCronExpression`. Recognizes only the shapes it emits;
 * every other cron expression becomes `{ kind: "raw" }` so hand-written
 * schedules survive editing untouched.
 */
export function parseCronExpression(cronExpression: string): Schedule {
	const raw: Schedule = { kind: "raw", cronExpression };
	const fields = cronExpression.trim().split(/\s+/);
	if (fields.length !== 5) {
		return raw;
	}
	const [minuteField, hourField, dom, month, dow] = fields;

	if (!/^\d{1,2}$/.test(minuteField) || !/^\d{1,2}$/.test(hourField)) {
		return raw;
	}
	const minute = Number(minuteField);
	const hour = Number(hourField);
	if (minute > 59 || hour > 23 || month !== "*") {
		return raw;
	}
	const time = partsToTime(minute, hour);

	if (dom === "1" && dow === "*") {
		return { kind: "monthly", time };
	}

	const dayIntervalMatch = /^\*\/(\d+)$/.exec(dom);
	if (dayIntervalMatch && dow === "*") {
		return {
			kind: "custom",
			interval: Number(dayIntervalMatch[1]),
			unit: "day",
			days: [],
			time,
		};
	}

	if (dom !== "*") {
		return raw;
	}

	if (dow === "*") {
		return { kind: "daily", time };
	}
	if (dow === "1-5") {
		return { kind: "weekdays", time };
	}

	const singleDay = parseWeekday(dow);
	if (singleDay !== null) {
		return { kind: "weekly", day: singleDay, time };
	}

	const biweeklyDays = parseBiweeklyDayList(dow);
	if (biweeklyDays !== null) {
		if (biweeklyDays.length === 1) {
			return { kind: "biweekly", day: biweeklyDays[0], time };
		}
		return {
			kind: "custom",
			interval: 2,
			unit: "week",
			days: biweeklyDays,
			time,
		};
	}

	const days = parseDayList(dow);
	if (days !== null) {
		return { kind: "custom", interval: 1, unit: "week", days, time };
	}

	return raw;
}

/** "09:05" -> "9:05" for display. */
function formatTime(time: string): string {
	return time.replace(/^0(\d)/, "$1");
}

function shortDayList(days: Weekday[]): string {
	return sortDays(days)
		.map((day) => WEEKDAY_SHORT_NAMES[day])
		.join(", ");
}

/** Human summary, e.g. "Every day · 9:00" or "Every two weeks on Monday · 9:30". */
export function describeSchedule(schedule: Schedule): string {
	switch (schedule.kind) {
		case "daily":
			return `Every day · ${formatTime(schedule.time)}`;
		case "weekdays":
			return `Weekdays · ${formatTime(schedule.time)}`;
		case "weekly":
			return `Every ${WEEKDAY_NAMES[schedule.day]} · ${formatTime(schedule.time)}`;
		case "biweekly":
			return `Every two weeks on ${WEEKDAY_NAMES[schedule.day]} · ${formatTime(schedule.time)}`;
		case "monthly":
			return `Monthly on the 1st · ${formatTime(schedule.time)}`;
		case "custom": {
			const time = formatTime(schedule.time);
			if (schedule.unit === "day") {
				return schedule.interval === 1
					? `Every day · ${time}`
					: `Every ${schedule.interval} days · ${time}`;
			}
			const days = shortDayList(schedule.days);
			return schedule.interval === 2
				? `Every two weeks on ${days} · ${time}`
				: `Every week on ${days} · ${time}`;
		}
		case "raw":
			return schedule.cronExpression;
	}
}

/**
 * Formats a run timestamp in the trigger's timezone, e.g.
 * "Today · 09:00", "Tomorrow · 09:00" or "Monday 14 July · 09:00".
 */
export function formatRunAt(iso: string, timezone: string): string {
	const date = new Date(iso);
	const dayKey = new Intl.DateTimeFormat("en-CA", {
		timeZone: timezone,
		year: "numeric",
		month: "2-digit",
		day: "2-digit",
	});
	const time = new Intl.DateTimeFormat("en-GB", {
		timeZone: timezone,
		hour: "2-digit",
		minute: "2-digit",
	}).format(date);

	const now = new Date();
	const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
	let dayLabel: string;
	if (dayKey.format(date) === dayKey.format(now)) {
		dayLabel = "Today";
	} else if (dayKey.format(date) === dayKey.format(tomorrow)) {
		dayLabel = "Tomorrow";
	} else {
		dayLabel = new Intl.DateTimeFormat("en-GB", {
			timeZone: timezone,
			weekday: "long",
			day: "numeric",
			month: "long",
		}).format(date);
	}
	return `${dayLabel} · ${time}`;
}

import { describe, expect, it } from "vitest";
import {
	buildCronExpression,
	describeSchedule,
	parseCronExpression,
	Schedule,
} from "./schedule";

describe("buildCronExpression", () => {
	it("maps every preset to its cron shape", () => {
		const cases: [Schedule, string][] = [
			[{ kind: "daily", time: "09:00" }, "0 9 * * *"],
			[{ kind: "weekdays", time: "08:30" }, "30 8 * * 1-5"],
			[{ kind: "weekly", day: 1, time: "07:30" }, "30 7 * * 1"],
			[{ kind: "biweekly", day: 1, time: "09:00" }, "0 9 * * 1#1,1#3"],
			[{ kind: "monthly", time: "09:00" }, "0 9 1 * *"],
			[
				{ kind: "custom", interval: 3, unit: "day", days: [], time: "09:00" },
				"0 9 */3 * *",
			],
			[
				{
					kind: "custom",
					interval: 1,
					unit: "week",
					days: [5, 1],
					time: "09:00",
				},
				"0 9 * * 1,5",
			],
			[
				{
					kind: "custom",
					interval: 2,
					unit: "week",
					days: [1, 5],
					time: "09:00",
				},
				"0 9 * * 1#1,1#3,5#1,5#3",
			],
			[{ kind: "raw", cronExpression: "*/15 * * * *" }, "*/15 * * * *"],
		];
		for (const [schedule, cron] of cases) {
			expect(buildCronExpression(schedule)).toBe(cron);
		}
	});

	it("returns null for inexpressible or incomplete schedules", () => {
		expect(
			buildCronExpression({
				kind: "custom",
				interval: 1,
				unit: "week",
				days: [],
				time: "09:00",
			}),
		).toBeNull();
		expect(
			buildCronExpression({
				kind: "custom",
				interval: 3,
				unit: "week",
				days: [1],
				time: "09:00",
			}),
		).toBeNull();
		expect(buildCronExpression({ kind: "daily", time: "25:00" })).toBeNull();
		expect(buildCronExpression({ kind: "daily", time: "" })).toBeNull();
	});
});

describe("parseCronExpression", () => {
	it("round-trips every emitted shape", () => {
		const crons = [
			"0 9 * * *",
			"30 8 * * 1-5",
			"30 7 * * 1",
			"0 9 * * 1#1,1#3",
			"0 9 1 * *",
			"0 9 */3 * *",
			"0 9 * * 1,5",
			"0 9 * * 1#1,1#3,5#1,5#3",
		];
		for (const cron of crons) {
			expect(buildCronExpression(parseCronExpression(cron))).toBe(cron);
		}
	});

	it("recognizes preset kinds", () => {
		expect(parseCronExpression("0 9 * * *").kind).toBe("daily");
		expect(parseCronExpression("30 8 * * 1-5").kind).toBe("weekdays");
		expect(parseCronExpression("30 7 * * 3")).toEqual({
			kind: "weekly",
			day: 3,
			time: "07:30",
		});
		expect(parseCronExpression("0 9 * * 1#1,1#3")).toEqual({
			kind: "biweekly",
			day: 1,
			time: "09:00",
		});
		expect(parseCronExpression("0 9 1 * *").kind).toBe("monthly");
		expect(parseCronExpression("0 9 */2 * *")).toEqual({
			kind: "custom",
			interval: 2,
			unit: "day",
			days: [],
			time: "09:00",
		});
		expect(parseCronExpression("0 9 * * 1,5")).toEqual({
			kind: "custom",
			interval: 1,
			unit: "week",
			days: [1, 5],
			time: "09:00",
		});
	});

	it("falls back to raw on anything it does not emit", () => {
		const crons = [
			"*/15 * * * *",
			"0 9,18 * * *",
			"0 9 * 6 *",
			"0 9 15 * 1",
			"0 9 * * 7",
			"not a cron",
			"0 9 * *",
		];
		for (const cron of crons) {
			expect(parseCronExpression(cron)).toEqual({
				kind: "raw",
				cronExpression: cron,
			});
		}
	});
});

describe("describeSchedule", () => {
	it("summarizes schedules for display", () => {
		expect(describeSchedule({ kind: "daily", time: "08:00" })).toBe(
			"Every day · 8:00",
		);
		expect(describeSchedule({ kind: "weekdays", time: "09:00" })).toBe(
			"Weekdays · 9:00",
		);
		expect(describeSchedule({ kind: "weekly", day: 1, time: "07:30" })).toBe(
			"Every Monday · 7:30",
		);
		expect(describeSchedule({ kind: "biweekly", day: 5, time: "09:30" })).toBe(
			"Every two weeks on Friday · 9:30",
		);
		expect(describeSchedule({ kind: "monthly", time: "09:00" })).toBe(
			"Monthly on the 1st · 9:00",
		);
		expect(
			describeSchedule({
				kind: "custom",
				interval: 2,
				unit: "week",
				days: [5, 1],
				time: "17:00",
			}),
		).toBe("Every two weeks on Mon, Fri · 17:00");
		expect(
			describeSchedule({ kind: "raw", cronExpression: "*/15 * * * *" }),
		).toBe("*/15 * * * *");
	});
});

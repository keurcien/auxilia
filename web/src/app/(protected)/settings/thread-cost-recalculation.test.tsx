import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ThreadCostRecalculation, {
	presetRange,
	toBackfillRange,
} from "./thread-cost-recalculation";
import {
	cancelCostBackfill,
	countBackfillThreads,
	getCostBackfill,
	startCostBackfill,
	type CostBackfill,
} from "@/lib/api/resources/thread-costs";

vi.mock("@/lib/api/resources/thread-costs", () => ({
	getCostBackfill: vi.fn(),
	startCostBackfill: vi.fn(),
	cancelCostBackfill: vi.fn(),
	countBackfillThreads: vi.fn(),
}));

const idle: CostBackfill = {
	jobId: "job",
	status: "idle",
	startAt: null,
	endAt: null,
	processed: 0,
	skipped: 0,
	failed: 0,
	incomplete: 0,
	lastError: null,
	total: 0,
	previousCost: "0",
	newCost: "0",
	unpricedModels: [],
	finishedAt: null,
};

// Mid-morning local, so the local day is 3 June in any timezone a test runs in.
const FIRST = new Date(2026, 5, 3, 10).toISOString();

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(getCostBackfill).mockResolvedValue(idle);
	vi.mocked(countBackfillThreads).mockResolvedValue({ threads: 13, firstCreatedAt: FIRST });
	vi.mocked(startCostBackfill).mockResolvedValue({ ...idle, status: "pending", total: 13 });
	vi.mocked(cancelCostBackfill).mockResolvedValue({ ...idle, status: "cancelled" });
});

describe("date ranges", () => {
	const today = new Date(2026, 9, 14); // 14 Oct 2026, local

	it("maps presets to inclusive local days", () => {
		expect(presetRange("7d", today)).toEqual({ from: "2026-10-08", to: "2026-10-14" });
		expect(presetRange("month", today)).toEqual({ from: "2026-10-01", to: "2026-10-14" });
		expect(presetRange("lastmonth", today)).toEqual({ from: "2026-09-01", to: "2026-09-30" });
		expect(presetRange("all", today)).toEqual({ from: "", to: "" });
		expect(presetRange("all", today, "2026-06-03")).toEqual({ from: "2026-06-03", to: "2026-10-14" });
		// January's "last month" crosses the year.
		expect(presetRange("lastmonth", new Date(2026, 0, 5))).toEqual({
			from: "2025-12-01",
			to: "2025-12-31",
		});
	});

	it("sends an exclusive end: the day after the last selected day", () => {
		expect(toBackfillRange("2026-10-01", "2026-10-14")).toEqual({
			startAt: new Date(2026, 9, 1).toISOString(),
			endAt: new Date(2026, 9, 15).toISOString(),
		});
		expect(toBackfillRange("", "")).toEqual({ startAt: null, endAt: null });
	});
});

it("counts the selected threads and starts a recalculation over them", async () => {
	render(<ThreadCostRecalculation />);
	fireEvent.change(screen.getByLabelText("Created on or after"), { target: { value: "2026-10-05" } });
	fireEvent.change(screen.getByLabelText("Created on or before"), { target: { value: "2026-10-11" } });
	const range = toBackfillRange("2026-10-05", "2026-10-11");
	await waitFor(() => { expect(countBackfillThreads).toHaveBeenLastCalledWith(range); });
	fireEvent.click(await screen.findByRole("button", { name: "Recalculate 13 threads" }));
	await waitFor(() => { expect(startCostBackfill).toHaveBeenCalledWith(range); });
	expect(await screen.findByRole("progressbar")).toHaveAttribute("aria-valuemax", "13");
});

it("fills All time from the first thread's day to today", async () => {
	render(<ThreadCostRecalculation />);
	await waitFor(() => { expect(countBackfillThreads).toHaveBeenCalledWith({ startAt: null, endAt: null }); });
	fireEvent.click(screen.getByRole("button", { name: "All time" }));
	await waitFor(() => expect(screen.getByLabelText("Created on or after")).toHaveValue("2026-06-03"));
	const today = new Date();
	const pad = (n: number) => String(n).padStart(2, "0");
	expect(screen.getByLabelText("Created on or before")).toHaveValue(
		`${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`,
	);
});

it("blocks reversed ranges and empty selections", async () => {
	render(<ThreadCostRecalculation />);
	fireEvent.change(screen.getByLabelText("Created on or after"), { target: { value: "2026-10-12" } });
	fireEvent.change(screen.getByLabelText("Created on or before"), { target: { value: "2026-10-05" } });
	expect(await screen.findByText("The start date is after the end date.")).toBeInTheDocument();
	expect(screen.getByRole("button", { name: /Recalculate/ })).toBeDisabled();

	vi.mocked(countBackfillThreads).mockResolvedValue({ threads: 0, firstCreatedAt: null });
	fireEvent.click(screen.getByRole("button", { name: "All time" }));
	expect(await screen.findByText("0 threads")).toBeInTheDocument();
	expect(screen.getByRole("button", { name: /Recalculate/ })).toBeDisabled();
});

it("shows progress and cancels a running job", async () => {
	vi.mocked(getCostBackfill).mockResolvedValue({
		...idle,
		status: "running",
		total: 13,
		processed: 4,
		skipped: 1,
	});
	render(<ThreadCostRecalculation />);
	expect(await screen.findByText("5 / 13")).toBeInTheDocument();
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	await waitFor(() => { expect(cancelCostBackfill).toHaveBeenCalledOnce(); });
});

it("summarises a finished job: cost change, counts and unpriced models", async () => {
	vi.mocked(getCostBackfill).mockResolvedValue({
		...idle,
		status: "complete",
		total: 13,
		processed: 11,
		incomplete: 2,
		previousCost: "21.40",
		newCost: "18.92",
		unpricedModels: ["deepseek-v4-flash"],
		finishedAt: new Date().toISOString(),
	});
	render(<ThreadCostRecalculation />);
	expect(await screen.findByText("11 threads recalculated")).toBeInTheDocument();
	expect(screen.getByText("21.40$")).toBeInTheDocument();
	expect(screen.getByText("→ 18.92$")).toBeInTheDocument();
	expect(screen.getByText("−2.48$")).toBeInTheDocument();
	expect(screen.getByText("2 incomplete")).toBeInTheDocument();
	expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
	expect(screen.getByText("just now")).toBeInTheDocument();
});

it("shows a failed start without claiming the job started", async () => {
	vi.mocked(startCostBackfill).mockRejectedValue(new Error("Offline"));
	render(<ThreadCostRecalculation />);
	fireEvent.click(await screen.findByRole("button", { name: "Recalculate 13 threads" }));
	expect(await screen.findByRole("alert")).toHaveTextContent("Could not start the recalculation");
	expect(screen.queryByRole("progressbar")).toBeNull();
});

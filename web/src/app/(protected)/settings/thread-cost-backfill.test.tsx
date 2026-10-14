import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import ThreadCostBackfill from "./thread-cost-backfill";
import { cancelCostBackfill, getCostBackfill, startCostBackfill, type CostBackfill } from "@/lib/api/resources/thread-costs";

vi.mock("@/lib/api/resources/thread-costs", () => ({
	getCostBackfill: vi.fn(), startCostBackfill: vi.fn(), cancelCostBackfill: vi.fn(),
}));

const idle: CostBackfill = {
	jobId: "job", status: "idle", startAt: null, endAt: null,
	processed: 0, skipped: 0, failed: 0, incomplete: 0, lastError: null,
};

beforeEach(() => {
	vi.resetAllMocks();
	vi.mocked(getCostBackfill).mockResolvedValue(idle);
	vi.mocked(startCostBackfill).mockResolvedValue({ ...idle, status: "pending" });
	vi.mocked(cancelCostBackfill).mockResolvedValue({ ...idle, status: "cancelled" });
});

it("submits the selected creation-date boundaries as local midnight instants", async () => {
	render(<ThreadCostBackfill />);
	await waitFor(() => expect(getCostBackfill).toHaveBeenCalled());
	fireEvent.change(screen.getByLabelText("Created on or after"), { target: { value: "2026-10-05" } });
	fireEvent.change(screen.getByLabelText("Created before"), { target: { value: "2026-10-12" } });
	fireEvent.click(screen.getByRole("button", { name: "Recalculate costs" }));
	await waitFor(() => expect(startCostBackfill).toHaveBeenCalledWith({
		startAt: new Date("2026-10-05T00:00:00").toISOString(),
		endAt: new Date("2026-10-12T00:00:00").toISOString(),
	}));
	expect(await screen.findByRole("button", { name: "Cancel" })).toBeEnabled();
});

it("prevents reversed ranges and overlapping jobs and supports cancellation", async () => {
	vi.mocked(getCostBackfill).mockResolvedValue({ ...idle, status: "running", processed: 4, incomplete: 1 });
	render(<ThreadCostBackfill />);
	expect(await screen.findByRole("status")).toHaveTextContent("4 calculated, 1 incomplete");
	expect(screen.getByRole("button", { name: "Recalculate costs" })).toBeDisabled();
	fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
	await waitFor(() => expect(cancelCostBackfill).toHaveBeenCalledOnce());
	await waitFor(() => expect(screen.getByRole("button", { name: "Recalculate costs" })).toBeEnabled());
	fireEvent.change(screen.getByLabelText("Created on or after"), { target: { value: "2026-10-12" } });
	fireEvent.change(screen.getByLabelText("Created before"), { target: { value: "2026-10-05" } });
	expect(screen.getByRole("button", { name: "Recalculate costs" })).toBeDisabled();
});

it("shows a failed request without claiming the job started", async () => {
	vi.mocked(startCostBackfill).mockRejectedValue(new Error("Offline"));
	render(<ThreadCostBackfill />);
	await waitFor(() => expect(getCostBackfill).toHaveBeenCalled());
	fireEvent.click(screen.getByRole("button", { name: "Recalculate costs" }));
	expect(await screen.findByRole("alert")).toHaveTextContent("Could not start cost backfill");
	expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
});

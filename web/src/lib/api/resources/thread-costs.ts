import { api } from "@/lib/api/client";

export interface CostBackfill {
	jobId: string;
	status: "idle" | "pending" | "running" | "complete" | "cancelled";
	startAt: string | null;
	endAt: string | null;
	processed: number;
	skipped: number;
	failed: number;
	incomplete: number;
	lastError: string | null;
}

export async function getCostBackfill(): Promise<CostBackfill> {
	return (await api.get<CostBackfill>("/thread-costs/backfill")).data;
}

export async function startCostBackfill(range: {
	startAt: string | null;
	endAt: string | null;
}): Promise<CostBackfill> {
	return (await api.post<CostBackfill>("/thread-costs/backfill", range)).data;
}

export async function cancelCostBackfill(): Promise<CostBackfill> {
	return (await api.delete<CostBackfill>("/thread-costs/backfill")).data;
}

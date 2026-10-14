import { api } from "@/lib/api/client";

/** Token buckets: `input` excludes cache reads and writes, so the four sum to `total`. */
export interface CostBuckets<T> {
	input: T;
	inputCacheRead: T;
	inputCacheCreation: T;
	output: T;
	total: T;
}

/** Live estimate from the thread's checkpoints, in USD. Amounts are decimal strings. */
export interface ThreadCost {
	threadId: string;
	complete: boolean;
	totalCost: string | null;
	knownCost: string;
	callCount: number;
	unpricedCallCount: number;
	usageDetails: CostBuckets<number>;
	/** Priced calls only; `total` equals `knownCost`. */
	costDetails: CostBuckets<string>;
}

export async function getThreadCost(threadId: string): Promise<ThreadCost> {
	return (await api.get<ThreadCost>(`/threads/${threadId}/cost`)).data;
}

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
	/** Threads in range when queued — the progress denominator. */
	total: number;
	/** Saved cost of the updated threads before and after, in USD (decimal strings). */
	previousCost: string;
	newCost: string;
	/** Models that had calls with no price set. */
	unpricedModels: string[];
	finishedAt: string | null;
}

export interface BackfillRange {
	startAt: string | null;
	endAt: string | null;
}

export interface ThreadCount {
	threads: number;
	/** Earliest creation date in the range; null when it holds no threads. */
	firstCreatedAt: string | null;
}

/** Threads a recalculation over this range would visit. */
export async function countBackfillThreads(range: BackfillRange): Promise<ThreadCount> {
	const params = Object.fromEntries(
		Object.entries(range).filter(([, value]) => value !== null),
	);
	return (await api.get<ThreadCount>("/thread-costs/backfill/count", { params })).data;
}

export async function getCostBackfill(): Promise<CostBackfill> {
	return (await api.get<CostBackfill>("/thread-costs/backfill")).data;
}

export async function startCostBackfill(range: BackfillRange): Promise<CostBackfill> {
	return (await api.post<CostBackfill>("/thread-costs/backfill", range)).data;
}

export async function cancelCostBackfill(): Promise<CostBackfill> {
	return (await api.delete<CostBackfill>("/thread-costs/backfill")).data;
}

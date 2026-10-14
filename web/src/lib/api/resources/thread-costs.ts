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

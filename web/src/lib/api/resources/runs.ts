/**
 * Run resource — the cross-thread run views under `/runs`.
 * Per-thread runs are on the thread resource (`listThreadRuns`).
 */
import { api } from "@/lib/api/client";
import type { Run } from "@/types/runs";

/**
 * The caller's in-flight runs, plus runs that finished within the last
 * `recentSeconds` (capped server-side at one hour) so a terminal transition
 * cannot fall between two polls.
 */
export async function listActiveRuns(recentSeconds: number): Promise<Run[]> {
	const response = await api.get<Run[]>("/runs/active", {
		params: { recentSeconds },
	});
	return response.data;
}

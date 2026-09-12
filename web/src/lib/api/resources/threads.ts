/**
 * Thread resource — `/threads` and the per-agent thread list.
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 */
import { api } from "@/lib/api/client";
import type { Paginated } from "@/types/api";
import type { Run } from "@/types/runs";
import type { AgentThread, Thread, ThreadCreate, ThreadRead } from "@/types/threads";

export type PageParams = { limit: number; offset: number };

/** The caller's threads, newest first. */
export async function listThreads(page: PageParams): Promise<Paginated<Thread>> {
	const response = await api.get<Paginated<Thread>>("/threads", { params: page });
	return response.data;
}

/** Every user's threads on one agent — admin/owner only (403 otherwise). */
export async function listAgentThreads(
	agentId: string,
	page: PageParams,
): Promise<Paginated<AgentThread>> {
	const response = await api.get<Paginated<AgentThread>>(
		`/agents/${agentId}/threads`,
		{ params: page },
	);
	return response.data;
}

/** Metadata + viewer role. The conversation comes from the protocol snapshot. */
export async function readThread(threadId: string): Promise<ThreadRead> {
	const response = await api.get<ThreadRead>(`/threads/${threadId}`);
	return response.data;
}

export async function createThread(payload: ThreadCreate): Promise<Thread> {
	const response = await api.post<Thread>("/threads", payload);
	return response.data;
}

export async function renameThread(
	threadId: string,
	firstMessageContent: string,
): Promise<void> {
	await api.patch(`/threads/${threadId}`, { firstMessageContent });
}

export async function deleteThread(threadId: string): Promise<void> {
	await api.delete(`/threads/${threadId}`);
}

/** The thread's runs, operational state only (status, error, timestamps). */
export async function listThreadRuns(threadId: string): Promise<Run[]> {
	const response = await api.get<Run[]>(`/threads/${threadId}/runs`);
	return response.data;
}

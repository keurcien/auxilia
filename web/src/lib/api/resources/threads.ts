/**
 * Thread resource — `/threads` and the per-agent thread list.
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 */
import { api } from "@/lib/api/client";
import type { Paginated } from "@/types/api";
import type { QueuedPrompt, Run } from "@/types/runs";
import type { AgentThread, Thread, ThreadCreate, ThreadRead } from "@/types/threads";

export type PageParams = { limit: number; offset: number };
export type ThreadPageParams = PageParams & { q?: string };

/** The caller's threads, newest first. */
export async function listThreads(
	page: ThreadPageParams,
): Promise<Paginated<Thread>> {
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

export async function listQueuedPrompts(
	threadId: string,
): Promise<QueuedPrompt[]> {
	const response = await api.get<QueuedPrompt[]>(
		`/threads/${threadId}/runs/queue`,
	);
	return response.data;
}

export async function enqueuePrompt(
	threadId: string,
	text: string,
): Promise<QueuedPrompt> {
	const response = await api.post<QueuedPrompt>(
		`/threads/${threadId}/runs/queue`,
		{ text },
	);
	return response.data;
}

export async function updateQueuedPrompt(
	threadId: string,
	runId: string,
	text: string,
): Promise<QueuedPrompt> {
	const response = await api.patch<QueuedPrompt>(
		`/threads/${threadId}/runs/queue/${runId}`,
		{ text },
	);
	return response.data;
}

export async function beginQueuedPromptEdit(
	threadId: string,
	runId: string,
): Promise<void> {
	await api.post(`/threads/${threadId}/runs/queue/${runId}/edit`);
}

export async function endQueuedPromptEdit(
	threadId: string,
	runId: string,
): Promise<void> {
	await api.delete(`/threads/${threadId}/runs/queue/${runId}/edit`);
}

export async function removeQueuedPrompt(
	threadId: string,
	runId: string,
): Promise<void> {
	await api.delete(`/threads/${threadId}/runs/queue/${runId}`);
}

export async function reorderQueuedPrompts(
	threadId: string,
	orderedIds: string[],
): Promise<QueuedPrompt[]> {
	const response = await api.put<QueuedPrompt[]>(
		`/threads/${threadId}/runs/queue/order`,
		{ orderedIds },
	);
	return response.data;
}

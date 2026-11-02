/**
 * Thread resource — `/threads` and the per-agent thread list.
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 */
import { api } from "@/lib/api/client";
import type { PromptInputMessage } from "@/components/ai-elements/prompt-input";
import type { Paginated } from "@/types/api";
import type { HumanInput } from "@/lib/thread-session/build-content";
import type { QueuedPrompt, Run } from "@/types/runs";
import type {
	AgentThread,
	Thread,
	ThreadCreate,
	ThreadRead,
	ThreadResourceSettings,
} from "@/types/threads";

export type PageParams = { limit: number; offset: number };
export type ThreadPageParams = PageParams & { q?: string };

export interface ConversationShare {
	id: string;
	threadId: string;
	token: string;
	createdAt: string | null;
}

export interface PublicConversationArtifact {
	id: string;
	tool_call_id: string | null;
	title: string;
	filename: string;
	mime_type: string;
	size: number;
}

export interface PublicConversationRun {
	id: string;
	status: string;
	created_at: string;
	updated_at: string;
	started_at: string | null;
	kind: "prompt" | "resume" | "regenerate" | "other";
	input_message_id: string | null;
}

export interface PublicConversation {
	id: string;
	title: string | null;
	published_at: string | null;
	agent: {
		name: string;
		emoji: string | null;
		color: string | null;
	};
	model_id: string | null;
	model_name: string | null;
	memories_enabled: boolean | null;
	cost: {
		known_cost: string;
		complete: boolean;
		call_count: number;
		unpriced_call_count: number;
		total_tokens: number;
		usage_details?: {
			input: number;
			input_cache_read: number;
			input_cache_creation: number;
			output: number;
			total: number;
		} | null;
		cost_details?: {
			input: string;
			input_cache_read: string;
			input_cache_creation: string;
			output: string;
			total: string;
		} | null;
	} | null;
	runs: PublicConversationRun[];
	tool_servers?: Array<{
		name: string;
		icon_url: string | null;
		tool_names?: string[];
	}>;
	messages: Record<string, unknown>[];
	artifacts: PublicConversationArtifact[];
}

type QueuedPromptWire = Omit<QueuedPrompt, "attachments"> & {
	attachments?: QueuedPrompt["attachments"];
};

const normalizeQueuedPrompt = (prompt: QueuedPromptWire): QueuedPrompt => ({
	...prompt,
	attachments: prompt.attachments ?? [],
});

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

/** Create a thread, persist its files and enqueue its first run atomically. */
export async function startThread(
	payload: ThreadCreate,
	message: PromptInputMessage,
	includeImages: boolean,
	storeFiles: boolean,
): Promise<Thread> {
	const form = new FormData();
	form.set(
		"payload",
		JSON.stringify({
			thread: {
				id: payload.id,
				agent_id: payload.agentId,
				model_id: payload.modelId,
				reasoning_effort: payload.reasoningEffort,
				project_id: payload.projectId,
				folder_id: payload.folderId,
				tool_mode: payload.toolMode,
				memories_enabled: payload.memoriesEnabled,
				disabled_mcp_server_ids: payload.disabledMcpServerIds,
				disabled_skill_ids: payload.disabledSkillIds,
				disabled_sandbox_ids: payload.disabledSandboxIds,
				disabled_subagent_ids: payload.disabledSubagentIds,
			},
			message_text: message.text ?? "",
			include_images: includeImages,
			store_files: storeFiles,
		}),
	);
	for (const file of message.files ?? []) {
		const blob = await (await fetch(file.url)).blob();
		form.append("files", blob, file.filename || "file");
	}
	const response = await api.post<Thread>("/threads/start", form);
	return response.data;
}

export async function renameThread(
	threadId: string,
	firstMessageContent: string,
): Promise<void> {
	await api.patch(`/threads/${threadId}`, { firstMessageContent });
}

export async function updateThreadPlacement(
	threadId: string,
	projectId: string | null,
	folderId: string | null,
): Promise<Thread> {
	const response = await api.put<Thread>(`/threads/${threadId}/placement`, {
		projectId,
		folderId,
	});
	return response.data;
}

export async function updateThreadCompletion(
	threadId: string,
	completed: boolean,
): Promise<Thread> {
	const response = await api.put<Thread>(`/threads/${threadId}/completion`, {
		completed,
	});
	return response.data;
}

/**
 * Set the thread's model and reasoning effort for its next runs. `null`
 * effort = the model's default; a model change without an explicit effort
 * drops the previous model's choice.
 */
export async function updateThreadModel(
	threadId: string,
	modelId: string,
	reasoningEffort: string | null = null,
): Promise<Thread> {
	const response = await api.put<Thread>(`/threads/${threadId}/model`, {
		modelId,
		reasoningEffort,
	});
	return response.data;
}

export async function updateThreadResources(
	threadId: string,
	settings: ThreadResourceSettings,
): Promise<Thread> {
	const response = await api.put<Thread>(
		`/threads/${threadId}/resources`,
		settings,
	);
	return response.data;
}

export async function updateThreadMemories(
	threadId: string,
	memoriesEnabled: boolean,
): Promise<Thread> {
	const response = await api.put<Thread>(`/threads/${threadId}/memories`, {
		memoriesEnabled,
	});
	return response.data;
}

export async function deleteThread(threadId: string): Promise<void> {
	await api.delete(`/threads/${threadId}`);
}

export async function getConversationShare(
	threadId: string,
): Promise<ConversationShare | null> {
	const response = await api.get<ConversationShare | null>(
		`/threads/${threadId}/share`,
	);
	return response.data;
}

export async function createConversationShare(
	threadId: string,
): Promise<ConversationShare> {
	const response = await api.post<ConversationShare>(
		`/threads/${threadId}/share`,
	);
	return response.data;
}

export async function deleteConversationShare(threadId: string): Promise<void> {
	await api.delete(`/threads/${threadId}/share`);
}

export async function getPublicConversation(
	shareId: string,
	token: string,
): Promise<PublicConversation> {
	const response = await fetch(`/api/backend/public/conversations/${shareId}`, {
		headers: { "X-Auxilia-Share-Token": token },
		credentials: "omit",
		cache: "no-store",
	});
	if (!response.ok) throw new Error("This shared conversation is unavailable.");
	return (await response.json()) as PublicConversation;
}

export async function getPublicArtifact(
	shareId: string,
	artifactId: string,
	token: string,
): Promise<Blob> {
	const response = await fetch(
		`/api/backend/public/conversations/${shareId}/artifacts/${artifactId}/content`,
		{
			headers: { "X-Auxilia-Share-Token": token },
			credentials: "omit",
			cache: "no-store",
		},
	);
	if (!response.ok) throw new Error("This shared file is unavailable.");
	return response.blob();
}

/** The thread's runs, operational state only (status, error, timestamps). */
export async function listThreadRuns(threadId: string): Promise<Run[]> {
	const response = await api.get<Run[]>(`/threads/${threadId}/runs`);
	return response.data;
}

export async function getActiveRun(threadId: string): Promise<Run | null> {
	const response = await api.get<Run | null>(
		`/threads/${threadId}/runs/active`,
	);
	return response.data;
}

export async function retryFailedRun(threadId: string): Promise<Run> {
	const response = await api.post<Run>(`/threads/${threadId}/runs/retry`);
	return response.data;
}

export async function listQueuedPrompts(
	threadId: string,
): Promise<QueuedPrompt[]> {
	// The queue hook deduplicates in-flight list requests per thread: a
	// request that never settles would pin the composer in its loading state.
	const response = await api.get<QueuedPromptWire[]>(
		`/threads/${threadId}/runs/queue`,
		{ signal: AbortSignal.timeout(10_000) },
	);
	return response.data.map(normalizeQueuedPrompt);
}

export async function enqueuePrompt(
	threadId: string,
	input: HumanInput,
): Promise<QueuedPrompt> {
	const { content, attachments, displayText } = input;
	const response = await api.post<QueuedPromptWire>(
		`/threads/${threadId}/runs/queue`,
		{
			content,
			attachmentIds: attachments.map((attachment) => attachment.id),
			displayText,
			inlineTextFiles: input.inlineTextFiles,
			...(displayText.trim() ? { text: displayText } : {}),
		},
		// Enqueues are serialized by the queue hook: one request that never
		// settles would block every later prompt until a reload.
		{ signal: AbortSignal.timeout(15_000) },
	);
	return normalizeQueuedPrompt(response.data);
}

export async function updateQueuedPrompt(
	threadId: string,
	runId: string,
	text: string,
): Promise<QueuedPrompt> {
	const response = await api.patch<QueuedPromptWire>(
		`/threads/${threadId}/runs/queue/${runId}`,
		{ text },
	);
	return normalizeQueuedPrompt(response.data);
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

export async function sendQueuedPromptNow(
	threadId: string,
	runId: string,
): Promise<void> {
	await api.post(`/threads/${threadId}/runs/queue/${runId}/send-now`);
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
	const response = await api.put<QueuedPromptWire[]>(
		`/threads/${threadId}/runs/queue/order`,
		{ orderedIds },
	);
	return response.data.map(normalizeQueuedPrompt);
}

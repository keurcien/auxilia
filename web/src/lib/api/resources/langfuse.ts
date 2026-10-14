/**
 * Langfuse resource — the agent's instructions as a Langfuse prompt
 * (`/integrations/langfuse`, `/agents/{id}/langfuse-prompt`).
 *
 * Plain functions over the axios client; failures reject with `ApiError`.
 */
import { api } from "@/lib/api/client";

export interface LangfusePromptVersion {
	version: number;
	labels: string[];
	commitMessage: string | null;
	text: string;
	/** Who published it: auxilia's publisher, else Langfuse's author. */
	author: string | null;
	createdAt: string | null;
}

export interface LangfusePrompt {
	/** Null until the agent's instructions are first published. */
	production: LangfusePromptVersion | null;
	/** The saved instructions no longer match the production version. */
	diverged: boolean;
}

let statusRequest: Promise<boolean> | null = null;

/** Whether this deployment has Langfuse configured — fetched once per page load. */
export function isLangfuseEnabled(): Promise<boolean> {
	statusRequest ??= api
		.get<{ enabled: boolean }>("/integrations/langfuse")
		.then((response) => response.data.enabled)
		.catch(() => {
			statusRequest = null;
			return false;
		});
	return statusRequest;
}

export async function getLangfusePrompt(agentId: string): Promise<LangfusePrompt> {
	const response = await api.get<LangfusePrompt>(`/agents/${agentId}/langfuse-prompt`);
	return response.data;
}

export async function listLangfuseVersions(
	agentId: string,
): Promise<LangfusePromptVersion[]> {
	const response = await api.get<LangfusePromptVersion[]>(
		`/agents/${agentId}/langfuse-prompt/versions`,
	);
	return response.data;
}

/** Releases the agent's saved instructions as a new production version. */
export async function publishLangfusePrompt(
	agentId: string,
	commitMessage: string | null,
): Promise<LangfusePromptVersion> {
	const response = await api.post<LangfusePromptVersion>(
		`/agents/${agentId}/langfuse-prompt/publish`,
		{ commitMessage },
	);
	return response.data;
}

export async function promoteLangfuseVersion(
	agentId: string,
	version: number,
): Promise<LangfusePromptVersion> {
	const response = await api.post<LangfusePromptVersion>(
		`/agents/${agentId}/langfuse-prompt/versions/${version}/promote`,
	);
	return response.data;
}

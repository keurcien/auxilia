/**
 * Sandbox resource — `/sandboxes` (workspace code-execution backends).
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`.
 */
import { api } from "@/lib/api/client";
import type { BoundAgent } from "@/types/agents";
import type { Sandbox, SandboxProviderType, SandboxSecretHint } from "@/types/sandboxes";

export interface SandboxSave {
	name: string;
	description: string | null;
	url: string;
	config: Record<string, unknown>;
	/** Only sent when the user typed one; omitted = keep the stored secret. */
	secret?: string;
}

export type SandboxCreate = SandboxSave & { provider: SandboxProviderType };

export async function listSandboxes(): Promise<Sandbox[]> {
	const response = await api.get<Sandbox[]>("/sandboxes");
	return response.data;
}

export async function createSandbox(payload: SandboxCreate): Promise<Sandbox> {
	const response = await api.post<Sandbox>("/sandboxes", payload);
	return response.data;
}

export async function updateSandbox(
	sandboxId: string,
	payload: SandboxSave,
): Promise<Sandbox> {
	const response = await api.patch<Sandbox>(`/sandboxes/${sandboxId}`, payload);
	return response.data;
}

/** Delete a sandbox. Refused while agents still bind it unless `detachAgents`. */
export async function deleteSandbox(
	sandboxId: string,
	options: { detachAgents?: boolean } = {},
): Promise<void> {
	await api.delete(`/sandboxes/${sandboxId}`, {
		params: options.detachAgents ? { detachAgents: true } : undefined,
	});
}

/** Agents still bound to the sandbox — the delete-guard dialog lists them. */
export async function listSandboxAgents(sandboxId: string): Promise<BoundAgent[]> {
	const response = await api.get<BoundAgent[]>(`/sandboxes/${sandboxId}/agents`);
	return response.data;
}

/** The stored provider secret, masked. */
export async function getSandboxSecretHint(sandboxId: string): Promise<SandboxSecretHint> {
	const response = await api.get<SandboxSecretHint>(`/sandboxes/${sandboxId}/secret-hint`);
	return response.data;
}

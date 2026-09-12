/**
 * Model resource — `/model-providers`: the models members can pick, and the
 * admin-side catalog management (enable/disable, workspace default, whitelist sync).
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 */
import { api } from "@/lib/api/client";
import type { ManagedModel, Model, WhitelistSyncResult } from "@/types/models";

/** Models enabled for the workspace — what pickers offer. */
export async function listModels(): Promise<Model[]> {
	const response = await api.get<Model[]>("/model-providers/models");
	return response.data;
}

/** The whole catalog with its enablement flags — admin only (403 otherwise). */
export async function listManagedModels(): Promise<ManagedModel[]> {
	const response = await api.get<ManagedModel[]>(
		"/model-providers/models/manage",
	);
	return response.data;
}

/** Enable or disable one catalog model for the workspace. */
export async function setModelEnabled(
	provider: string,
	modelId: string,
	isEnabled: boolean,
): Promise<void> {
	await api.put(
		`/model-providers/models/${encodeURIComponent(provider)}/${encodeURIComponent(modelId)}`,
		{ isEnabled },
	);
}

/** Make one model the workspace default (preselects pickers, used by Slack). */
export async function setDefaultModel(
	provider: string,
	modelId: string,
): Promise<void> {
	await api.put("/model-providers/models/default", { provider, modelId });
}

/** Back to automatic: the first available model is used. */
export async function clearDefaultModel(): Promise<void> {
	await api.delete("/model-providers/models/default");
}

/** Re-pull the CDN whitelist; reports what was added and removed. */
export async function syncWhitelist(): Promise<WhitelistSyncResult> {
	const response = await api.post<WhitelistSyncResult>(
		"/model-providers/whitelist/sync",
	);
	return response.data;
}

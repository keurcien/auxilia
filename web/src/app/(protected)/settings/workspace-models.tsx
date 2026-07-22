"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { RefreshCw, Star } from "lucide-react";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { useModelsStore } from "@/stores/models-store";
import type { ManagedModel, WhitelistSyncResult } from "@/types/models";

const PROVIDER_LABELS = new Map<string, string>([
	["openai", "OpenAI"],
	["anthropic", "Anthropic"],
	["google", "Google"],
	["deepseek", "DeepSeek"],
	["xiaomi", "Xiaomi"],
	["openrouter", "OpenRouter"],
	["meta", "Meta"],
]);

function providerLabel(provider: string): string {
	return PROVIDER_LABELS.get(provider) ?? provider;
}

function apiErrorDetail(error: unknown): string | null {
	if (axios.isAxiosError(error)) {
		const data = error.response?.data as { detail?: string } | undefined;
		return data?.detail ?? null;
	}
	return null;
}

function syncSummary(result: WhitelistSyncResult): string {
	const changes = [
		result.added.length > 0 && `${result.added.length} added`,
		result.removed.length > 0 && `${result.removed.length} removed`,
	]
		.filter(Boolean)
		.join(", ");
	return `Catalog synced — ${changes || "no changes"} (${result.modelCount} models).`;
}

interface WorkspaceModelsProps {
	onForbidden: () => void;
}

export default function WorkspaceModels({ onForbidden }: WorkspaceModelsProps) {
	const refreshModels = useModelsStore((state) => state.refreshModels);
	const [models, setModels] = useState<ManagedModel[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [loadFailed, setLoadFailed] = useState(false);
	const [isSyncing, setIsSyncing] = useState(false);
	// Keys with a PUT in flight — a Set so overlapping toggles on different
	// rows don't re-enable each other's switch mid-request.
	const [pendingKeys, setPendingKeys] = useState<ReadonlySet<string>>(
		new Set(),
	);
	// Default changes rewrite every row's flag, so they are serialized: all
	// stars lock while one request is in flight.
	const [isDefaultUpdating, setIsDefaultUpdating] = useState(false);
	const [status, setStatus] = useState<{
		kind: "info" | "error";
		text: string;
	} | null>(null);

	// Latest-callback ref: keeps loadManaged's identity stable (its consumer
	// is a mount effect) without freezing the first render's onForbidden.
	const onForbiddenRef = useRef(onForbidden);
	useEffect(() => {
		onForbiddenRef.current = onForbidden;
	}, [onForbidden]);

	const loadManaged = useCallback(async () => {
		setIsLoading(true);
		setLoadFailed(false);
		try {
			const response = await api.get<ManagedModel[]>(
				"/model-providers/models/manage",
			);
			setModels(response.data);
		} catch (error: unknown) {
			if (axios.isAxiosError(error) && error.response?.status === 403) {
				onForbiddenRef.current();
			} else {
				console.error("Error fetching workspace models:", error);
				// Distinct from an empty catalog — "no providers configured"
				// would send the admin chasing the wrong problem.
				setLoadFailed(true);
			}
		} finally {
			setIsLoading(false);
		}
	}, []);

	useEffect(() => {
		void loadManaged();
	}, [loadManaged]);

	// Group rows by provider, preserving whitelist order.
	const providerGroups = useMemo(() => {
		const groups = new Map<string, ManagedModel[]>();
		for (const model of models) {
			const existing = groups.get(model.provider);
			if (existing) existing.push(model);
			else groups.set(model.provider, [model]);
		}
		return [...groups.entries()];
	}, [models]);

	const handleToggle = async (model: ManagedModel, isEnabled: boolean) => {
		const key = `${model.provider}/${model.modelId}`;
		setPendingKeys((prev) => new Set(prev).add(key));
		setStatus(null);
		// Optimistic flip; reverted on failure. Disabling the default also
		// clears its flag (the backend auto-unsets — back to automatic).
		setModels((prev) =>
			prev.map((m) =>
				m.provider === model.provider && m.modelId === model.modelId
					? { ...m, isEnabled, isDefault: isEnabled ? m.isDefault : false }
					: m,
			),
		);
		try {
			await api.put(
				`/model-providers/models/${encodeURIComponent(model.provider)}/${encodeURIComponent(model.modelId)}`,
				{ isEnabled },
			);
			// Every open model picker reflects the change without a reload.
			await refreshModels().catch(() => {});
		} catch (error: unknown) {
			setModels((prev) =>
				prev.map((m) =>
					m.provider === model.provider && m.modelId === model.modelId
						? { ...m, isEnabled: !isEnabled, isDefault: model.isDefault }
						: m,
				),
			);
			if (axios.isAxiosError(error) && error.response?.status === 403) {
				onForbidden();
			} else {
				setStatus({
					kind: "error",
					text:
						apiErrorDetail(error) ??
						`Could not update ${model.displayName}. Please retry.`,
				});
			}
		} finally {
			setPendingKeys((prev) => {
				const next = new Set(prev);
				next.delete(key);
				return next;
			});
		}
	};

	const handleSetDefault = async (model: ManagedModel) => {
		const key = `${model.provider}/${model.modelId}`;
		// Clicking the current default's star unsets it (back to automatic).
		const makeDefault = !model.isDefault;
		setIsDefaultUpdating(true);
		setPendingKeys((prev) => new Set(prev).add(key));
		setStatus(null);
		// Optimistic: exactly one default at a time — flag the target, clear
		// the rest.
		setModels((prev) =>
			prev.map((m) => ({
				...m,
				isDefault:
					makeDefault &&
					m.provider === model.provider &&
					m.modelId === model.modelId,
			})),
		);
		try {
			if (makeDefault) {
				await api.put("/model-providers/models/default", {
					provider: model.provider,
					modelId: model.modelId,
				});
			} else {
				await api.delete("/model-providers/models/default");
			}
			// Every open model picker preselects the new default without a reload.
			await refreshModels().catch(() => {});
		} catch (error: unknown) {
			// Refetch instead of reverting from a snapshot: the persisted state
			// is the only reliable source after a failure.
			await loadManaged();
			if (axios.isAxiosError(error) && error.response?.status === 403) {
				onForbidden();
			} else {
				setStatus({
					kind: "error",
					text:
						apiErrorDetail(error) ??
						`Could not update the default model. Please retry.`,
				});
			}
		} finally {
			setIsDefaultUpdating(false);
			setPendingKeys((prev) => {
				const next = new Set(prev);
				next.delete(key);
				return next;
			});
		}
	};

	const handleSync = async () => {
		setIsSyncing(true);
		setStatus(null);
		let summary: string;
		try {
			const syncResponse = await api.post<WhitelistSyncResult>(
				"/model-providers/whitelist/sync",
			);
			summary = syncSummary(syncResponse.data);
		} catch (error: unknown) {
			if (axios.isAxiosError(error) && error.response?.status === 403) {
				onForbidden();
			} else {
				setStatus({
					kind: "error",
					text: apiErrorDetail(error) ?? "Catalog sync failed. Please retry.",
				});
			}
			setIsSyncing(false);
			return;
		}
		// The sync itself succeeded — a refetch hiccup must not report it as
		// failed (the backend has already applied the new catalog).
		try {
			const managedResponse = await api.get<ManagedModel[]>(
				"/model-providers/models/manage",
			);
			setModels(managedResponse.data);
			setStatus({ kind: "info", text: summary });
		} catch {
			setStatus({
				kind: "info",
				text: `${summary} The list below could not be refreshed — reload the page.`,
			});
		} finally {
			setIsSyncing(false);
		}
		await refreshModels().catch(() => {});
	};

	return (
		<section className="mt-12">
			<div className="flex items-center justify-between mb-2">
				<h2 className="font-primary font-bold text-lg tracking-tight text-[#2A2F2D] dark:text-white">
					Workspace models
				</h2>
				<Button
					variant="outline"
					size="sm"
					className="gap-2 cursor-pointer"
					disabled={isSyncing}
					onClick={() => {
						void handleSync();
					}}
				>
					<RefreshCw className={isSyncing ? "h-4 w-4 animate-spin" : "h-4 w-4"} />
					Sync catalog
				</Button>
			</div>
			<p className="text-sm text-muted-foreground mb-3">
				Choose which models members can use in chats and triggers. New catalog
				models start disabled until you enable them. Star a model to make it
				the workspace default — it preselects model pickers and is used by
				Slack; without one, the first available model is used.
			</p>
			{status && (
				<p
					className={
						status.kind === "error"
							? "text-sm text-destructive mb-3"
							: "text-sm text-muted-foreground mb-3"
					}
				>
					{status.text}
				</p>
			)}

			<div className="rounded-[20px] border bg-card overflow-hidden">
				{isLoading ? (
					<div className="px-6 py-12 text-center text-muted-foreground">
						Loading...
					</div>
				) : loadFailed ? (
					<div className="px-6 py-12 text-center">
						<p className="text-muted-foreground mb-3">
							Could not load the workspace models.
						</p>
						<Button
							variant="outline"
							size="sm"
							className="cursor-pointer"
							onClick={() => {
								void loadManaged();
							}}
						>
							Retry
						</Button>
					</div>
				) : providerGroups.length === 0 ? (
					<div className="px-6 py-12 text-center text-muted-foreground">
						No providers configured. Set provider API keys in the backend
						environment to offer models.
					</div>
				) : (
					providerGroups.map(([provider, providerModels]) => (
						<div key={provider} className="border-b last:border-b-0">
							<div className="px-6 py-3 bg-muted/50 flex items-center justify-between">
								<span className="text-xs text-muted-foreground font-semibold uppercase tracking-wider">
									{providerLabel(provider)}
								</span>
								<span className="text-xs text-muted-foreground">
									{providerModels.filter((m) => m.isEnabled).length}/
									{providerModels.length} enabled
								</span>
							</div>
							{providerModels.map((model) => {
								const key = `${model.provider}/${model.modelId}`;
								return (
									<div
										key={key}
										className="px-6 py-3 border-t flex items-center justify-between gap-4 hover:bg-muted/30 transition-colors"
									>
										<div className="flex items-center gap-3 min-w-0">
											<ModelSelectorLogo
												provider={model.chefSlug}
												className="size-4 shrink-0"
											/>
											<div className="flex flex-col gap-0.5 min-w-0">
												<div className="flex items-center gap-2 flex-wrap">
													<span className="text-sm font-medium text-foreground">
														{model.displayName}
													</span>
													{model.isDefault && <Badge>Default</Badge>}
													{model.deprecated && (
														<Badge variant="destructive">
															No longer supported
														</Badge>
													)}
													{model.multimodal && (
														<Badge variant="secondary">Multimodal</Badge>
													)}
													{model.supportsStructuredOutput && (
														<Badge variant="secondary">Structured output</Badge>
													)}
												</div>
												<span className="text-xs text-muted-foreground font-mono truncate">
													{model.modelId}
												</span>
											</div>
										</div>
										<div className="flex items-center gap-1">
											<Button
												variant="ghost"
												size="icon"
												className="h-8 w-8 cursor-pointer"
												aria-label={
													model.isDefault
														? `Unset ${model.displayName} as the workspace default`
														: `Set ${model.displayName} as the workspace default`
												}
												title={
													model.isDefault
														? "Unset as default (back to automatic)"
														: "Set as workspace default"
												}
												// Only an enabled, supported model can be the default;
												// default changes are serialized (they rewrite every
												// row's flag), so all stars lock while one is in flight.
												disabled={
													pendingKeys.has(key) ||
													isSyncing ||
													isDefaultUpdating ||
													!model.isEnabled ||
													model.deprecated
												}
												onClick={() => {
													void handleSetDefault(model);
												}}
											>
												<Star
													className={
														model.isDefault
															? "h-4 w-4 fill-current text-foreground"
															: "h-4 w-4 text-muted-foreground"
													}
												/>
											</Button>
											<Switch
												checked={model.isEnabled}
												aria-label={`Enable ${model.displayName} (${model.modelId})`}
												// Deprecated rows can only be turned off; a sync in
												// flight would overwrite concurrent toggles, so rows
												// lock while it runs.
												disabled={
													pendingKeys.has(key) ||
													isSyncing ||
													(model.deprecated && !model.isEnabled)
												}
												onCheckedChange={(checked) => {
													void handleToggle(model, checked);
												}}
											/>
										</div>
									</div>
								);
							})}
						</div>
					))
				)}
			</div>
		</section>
	);
}

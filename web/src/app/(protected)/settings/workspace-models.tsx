"use client";

import { useEffect, useMemo, useState } from "react";
import axios from "axios";
import { RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { api } from "@/lib/api/client";
import { useModelsStore } from "@/stores/models-store";
import type { ManagedModel, WhitelistSyncResult } from "@/types/models";

const PROVIDER_LABELS: Record<string, string> = {
	openai: "OpenAI",
	anthropic: "Anthropic",
	google: "Google",
	deepseek: "DeepSeek",
	xiaomi: "Xiaomi",
	openrouter: "OpenRouter",
	meta: "Meta",
};

function providerLabel(provider: string): string {
	return PROVIDER_LABELS[provider] ?? provider;
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
	const [isSyncing, setIsSyncing] = useState(false);
	const [pendingKey, setPendingKey] = useState<string | null>(null);
	const [status, setStatus] = useState<{
		kind: "info" | "error";
		text: string;
	} | null>(null);

	useEffect(() => {
		const fetchManaged = async () => {
			try {
				const response = await api.get<ManagedModel[]>(
					"/model-providers/models/manage",
				);
				setModels(response.data);
			} catch (error: unknown) {
				if (axios.isAxiosError(error) && error.response?.status === 403) {
					onForbidden();
				} else {
					console.error("Error fetching workspace models:", error);
				}
			} finally {
				setIsLoading(false);
			}
		};
		void fetchManaged();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

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
		setPendingKey(key);
		setStatus(null);
		// Optimistic flip; reverted on failure.
		setModels((prev) =>
			prev.map((m) =>
				m.provider === model.provider && m.modelId === model.modelId
					? { ...m, isEnabled }
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
						? { ...m, isEnabled: !isEnabled }
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
			setPendingKey(null);
		}
	};

	const handleSync = async () => {
		setIsSyncing(true);
		setStatus(null);
		try {
			const syncResponse = await api.post<WhitelistSyncResult>(
				"/model-providers/whitelist/sync",
			);
			const managedResponse = await api.get<ManagedModel[]>(
				"/model-providers/models/manage",
			);
			setModels(managedResponse.data);
			setStatus({ kind: "info", text: syncSummary(syncResponse.data) });
			await refreshModels().catch(() => {});
		} catch (error: unknown) {
			if (axios.isAxiosError(error) && error.response?.status === 403) {
				onForbidden();
			} else {
				setStatus({
					kind: "error",
					text: apiErrorDetail(error) ?? "Catalog sync failed. Please retry.",
				});
			}
		} finally {
			setIsSyncing(false);
		}
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
				models start disabled until you enable them.
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
										<div className="flex flex-col gap-0.5 min-w-0">
											<div className="flex items-center gap-2 flex-wrap">
												<span className="text-sm font-medium text-foreground">
													{model.displayName}
												</span>
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
										<Switch
											checked={model.isEnabled}
											// Deprecated rows can only be turned off; the model is
											// gone from the catalog, so re-enabling is meaningless.
											disabled={
												pendingKey === key ||
												(model.deprecated && !model.isEnabled)
											}
											onCheckedChange={(checked) => {
												void handleToggle(model, checked);
											}}
										/>
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

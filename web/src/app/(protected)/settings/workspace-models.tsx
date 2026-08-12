"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { RefreshCw, Star } from "lucide-react";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import { HeaderButton } from "@/components/layout/subpage-header";
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

/** Mono-caps chip on a model row (DEFAULT / capabilities / deprecation). */
function ModelBadge({
	tone,
	children,
}: {
	tone: "accent" | "neutral" | "destructive";
	children: React.ReactNode;
}) {
	const toneClass =
		tone === "accent"
			? "bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal"
			: tone === "destructive"
				? "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/10"
				: "bg-hover text-subtle dark:bg-white/10 dark:text-panel-body";
	return (
		<span
			className={`shrink-0 rounded-[4px] px-[7px] py-[2px] font-mono text-[9px] font-semibold tracking-[0.05em] ${toneClass}`}
		>
			{children}
		</span>
	);
}

interface WorkspaceModelsProps {
	onForbidden: () => void;
	/** Reports the catalog size so the settings rail can show a count. */
	onCountChange?: (count: number) => void;
}

export default function WorkspaceModels({
	onForbidden,
	onCountChange,
}: WorkspaceModelsProps) {
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

	const onCountChangeRef = useRef(onCountChange);
	useEffect(() => {
		onCountChangeRef.current = onCountChange;
	}, [onCountChange]);
	useEffect(() => {
		onCountChangeRef.current?.(models.length);
	}, [models.length]);

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
		<div>
			<div className="mb-1.5 flex items-baseline gap-2.5">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-subtle dark:text-panel-dim">
					WORKSPACE MODELS
				</span>
				<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
					admin
				</span>
				<span className="flex-1" />
				<HeaderButton
					accent
					className="gap-1.5 px-3.5 py-[7px] text-[12.5px]"
					disabled={isSyncing}
					onClick={() => {
						void handleSync();
					}}
				>
					<RefreshCw
						className={isSyncing ? "size-[13px] animate-spin" : "size-[13px]"}
					/>
					Sync catalog
				</HeaderButton>
			</div>
			<p className="mb-3.5 max-w-[640px] text-[13px] leading-[1.55] text-subtle text-pretty dark:text-panel-body">
				Choose which models members can use in chats and triggers. New catalog
				models start disabled. Star a model to make it the workspace default —
				it preselects pickers and is used by Slack; without one, the first
				available model is used.
			</p>
			{status && (
				<p
					className={`mb-3 text-[13px] font-medium ${
						status.kind === "error"
							? "text-destructive"
							: "text-subtle dark:text-panel-body"
					}`}
				>
					{status.text}
				</p>
			)}

			<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
				{isLoading ? (
					<div className="px-4 py-12 text-center text-[14px] font-medium text-faint dark:text-muted-foreground">
						Loading…
					</div>
				) : loadFailed ? (
					<div className="px-4 py-12 text-center">
						<p className="mb-3 text-[14px] font-medium text-faint dark:text-muted-foreground">
							Could not load the workspace models.
						</p>
						<HeaderButton
							className="mx-auto"
							onClick={() => {
								void loadManaged();
							}}
						>
							Retry
						</HeaderButton>
					</div>
				) : providerGroups.length === 0 ? (
					<div className="px-4 py-12 text-center text-[14px] font-medium text-faint dark:text-muted-foreground">
						No providers configured. Set provider API keys in the backend
						environment to offer models.
					</div>
				) : (
					providerGroups.map(([provider, providerModels]) => (
						<div key={provider}>
							<div className="flex items-center border-b border-hairline bg-sidebar px-4 py-[9px] dark:border-white/5 dark:bg-white/[0.03]">
								<span className="font-mono text-[10px] font-semibold uppercase tracking-[0.09em] text-subtle dark:text-panel-dim">
									{providerLabel(provider)}
								</span>
								<span className="ml-auto font-mono text-[10.5px] text-meta dark:text-panel-dim">
									{providerModels.filter((m) => m.isEnabled).length}/
									{providerModels.length} enabled
								</span>
							</div>
							{providerModels.map((model) => {
								const key = `${model.provider}/${model.modelId}`;
								return (
									<div
										key={key}
										className="flex items-center gap-3 border-b border-hairline px-4 py-3 transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5"
									>
										<ModelSelectorLogo
											provider={model.chefSlug}
											className={
												model.isEnabled
													? "size-4 shrink-0"
													: "size-4 shrink-0 opacity-45"
											}
										/>
										<div className="min-w-0 flex-1">
											<div className="flex flex-wrap items-center gap-2">
												<span
													className={`text-[13.5px] font-semibold ${
														model.isEnabled
															? "text-foreground"
															: "text-meta dark:text-panel-dim"
													}`}
												>
													{model.displayName}
												</span>
												{model.isDefault && (
													<ModelBadge tone="accent">DEFAULT</ModelBadge>
												)}
												{model.deprecated && (
													<ModelBadge tone="destructive">
														NO LONGER SUPPORTED
													</ModelBadge>
												)}
												{model.multimodal && (
													<ModelBadge tone="neutral">MULTIMODAL</ModelBadge>
												)}
												{model.supportsStructuredOutput && (
													<ModelBadge tone="neutral">
														STRUCTURED OUTPUT
													</ModelBadge>
												)}
											</div>
											<span
												className={`mt-0.5 block truncate font-mono text-[10.5px] ${
													model.isEnabled
														? "text-meta dark:text-panel-dim"
														: "text-faint dark:text-panel-dim/70"
												}`}
											>
												{model.modelId}
											</span>
										</div>
										<button
											type="button"
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
											className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] transition-colors hover:bg-hover disabled:cursor-default disabled:opacity-50 disabled:hover:bg-transparent dark:hover:bg-white/10"
										>
											<Star
												className={
													model.isDefault
														? "size-[15px] fill-current text-ink dark:text-white"
														: "size-[15px] text-faint"
												}
											/>
										</button>
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
											className="cursor-pointer data-[state=checked]:bg-petrol"
										/>
									</div>
								);
							})}
						</div>
					))
				)}
			</div>
		</div>
	);
}

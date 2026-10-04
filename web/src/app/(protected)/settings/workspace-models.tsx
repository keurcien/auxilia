"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, RefreshCw, Search, Star, Trash2 } from "lucide-react";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import { HeaderButton } from "@/components/layout/subpage-header";
import {
	Collapsible,
	CollapsibleContent,
	CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import * as modelsApi from "@/lib/api/resources/models";
import { isApiError } from "@/lib/api/errors";
import { useModelsStore } from "@/stores/models-store";
import type {
	ManagedModel,
	ModelProviderConfig,
	WhitelistSyncResult,
} from "@/types/models";

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
	return isApiError(error) ? error.detail : null;
}

function syncSummary(result: WhitelistSyncResult): string {
	const changes = [
		result.added.length > 0 && `${result.added.length} added`,
		result.removed.length > 0 && `${result.removed.length} removed`,
	]
		.filter(Boolean)
		.join(", ");
	return `Catalog synced, ${changes || "no changes"} (${result.modelCount} models).`;
}

function orderManagedModels(models: ManagedModel[]): ManagedModel[] {
	return [...models].sort(
		(a, b) => Number(b.isEnabled) - Number(a.isEnabled),
	);
}

function preserveManagedModelOrder(
	current: ManagedModel[],
	incoming: ManagedModel[],
): ManagedModel[] {
	const byKey = new Map(
		incoming.map((model) => [`${model.provider}/${model.modelId}`, model]),
	);
	const ordered = current.flatMap((model) => {
		const updated = byKey.get(`${model.provider}/${model.modelId}`);
		if (!updated) return [];
		byKey.delete(`${model.provider}/${model.modelId}`);
		return [updated];
	});
	return [...ordered, ...byKey.values()];
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
			className={`shrink-0 rounded-[4px] px-[7px] py-[2px] text-[9px] font-semibold ${toneClass}`}
		>
			{children}
		</span>
	);
}

interface WorkspaceModelsProps {
	onForbidden: () => void;
	/** Reports usable models: enabled and backed by configured credentials. */
	onCountChange?: (count: number) => void;
	/** Refresh the remote catalog once before the initial list is loaded. */
	syncOnMount?: boolean;
	showSyncControl?: boolean;
}

export default function WorkspaceModels({
	onForbidden,
	onCountChange,
	syncOnMount = false,
	showSyncControl = true,
}: WorkspaceModelsProps) {
	const refreshModels = useModelsStore((state) => state.refreshModels);
	const [models, setModels] = useState<ManagedModel[]>([]);
	const [providers, setProviders] = useState<ModelProviderConfig[]>([]);
	const [searchQuery, setSearchQuery] = useState("");
	const [openProviders, setOpenProviders] = useState<ReadonlySet<string>>(
		new Set(),
	);
	const [keyDrafts, setKeyDrafts] = useState<
		Partial<Record<string, string>>
	>({});
	const [pendingProviders, setPendingProviders] = useState<ReadonlySet<string>>(
		new Set(),
	);
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

	const hasSyncedOnMountRef = useRef(false);
	const hasLoadedModelsRef = useRef(false);
	useEffect(() => {
		if (!hasLoadedModelsRef.current) return;
		const configuredProviders = new Set(
			providers
				.filter((provider) => provider.isConfigured)
				.map((provider) => provider.name),
		);
		onCountChangeRef.current?.(
			models.filter(
				(model) =>
					model.isEnabled && configuredProviders.has(model.provider),
			).length,
		);
	}, [models, providers]);

	const loadManaged = useCallback(async () => {
		setIsLoading(true);
		setLoadFailed(false);
		if (syncOnMount && !hasSyncedOnMountRef.current) {
			hasSyncedOnMountRef.current = true;
			setIsSyncing(true);
			try {
				await modelsApi.syncWhitelist();
			} catch (error: unknown) {
				if (isApiError(error) && error.status === 403) {
					onForbiddenRef.current();
					setIsLoading(false);
					return;
				}
				setStatus({
					kind: "error",
					text:
						apiErrorDetail(error) ??
						"Catalog sync failed. The existing catalog is shown instead.",
				});
			} finally {
				setIsSyncing(false);
			}
		}
		try {
			const [managed, providerConfigs] = await Promise.all([
				modelsApi.listManagedModels(),
				modelsApi.listProviderConfigs(),
			]);
			setModels(orderManagedModels(managed));
			setProviders(providerConfigs);
			setOpenProviders(
				new Set(
					providerConfigs
						.filter((provider) => provider.isConfigured)
						.map((provider) => provider.name),
				),
			);
			// Only model state originating from a successful fetch reports a count;
			// the initial empty array must not show a misleading "Models 0".
			hasLoadedModelsRef.current = true;
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) {
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
	}, [syncOnMount]);

	useEffect(() => {
		const timeoutId = window.setTimeout(() => {
			void loadManaged();
		}, 0);
		return () => {
			window.clearTimeout(timeoutId);
		};
	}, [loadManaged]);

	// The order is frozen from the last load: toggling a row updates it in place
	// instead of making it jump between the enabled and disabled sections.
	const providerGroups = useMemo(() => {
		const query = searchQuery.trim().toLocaleLowerCase();
		return providers
			.map((provider) => {
				const allProviderModels = models.filter(
					(model) => model.provider === provider.name,
				);
				const providerModels = allProviderModels.filter(
					(model) =>
						!query ||
						model.displayName.toLocaleLowerCase().includes(query) ||
						model.modelId.toLocaleLowerCase().includes(query),
				);
				return {
					provider,
					models: providerModels,
					enabledCount: allProviderModels.filter((model) => model.isEnabled)
						.length,
					totalCount: allProviderModels.length,
				};
			})
			.filter(({ models: providerModels }) => !query || providerModels.length > 0);
	}, [models, providers, searchQuery]);

	const updateProvider = (updated: ModelProviderConfig) => {
		setProviders((current) =>
			current.map((provider) =>
				provider.name === updated.name ? updated : provider,
			),
		);
	};

	const handleProviderKeySave = async (provider: ModelProviderConfig) => {
		const apiKey = keyDrafts[provider.name]?.trim();
		if (!apiKey) return;
		setPendingProviders((current) => new Set(current).add(provider.name));
		setStatus(null);
		try {
			updateProvider(
				await modelsApi.setProviderApiKey(provider.name, apiKey),
			);
			setKeyDrafts((current) => ({ ...current, [provider.name]: "" }));
			setStatus({
				kind: "info",
				text: `${providerLabel(provider.name)} API key saved.`,
			});
			await refreshModels().catch(() => {});
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) {
				onForbidden();
			} else {
				setStatus({
					kind: "error",
					text:
						apiErrorDetail(error) ??
						`Could not save the ${providerLabel(provider.name)} API key.`,
				});
			}
		} finally {
			setPendingProviders((current) => {
				const next = new Set(current);
				next.delete(provider.name);
				return next;
			});
		}
	};

	const handleProviderKeyDelete = async (provider: ModelProviderConfig) => {
		setPendingProviders((current) => new Set(current).add(provider.name));
		setStatus(null);
		try {
			const updated = await modelsApi.deleteProviderApiKey(provider.name);
			updateProvider(updated);
			if (!updated.isConfigured) {
				setModels((current) =>
					current.map((model) =>
						model.provider === provider.name
							? { ...model, isDefault: false }
							: model,
					),
				);
			}
			setKeyDrafts((current) => ({ ...current, [provider.name]: "" }));
			setStatus({
				kind: "info",
				text:
					updated.source === "environment"
						? `${providerLabel(provider.name)} now uses the deployment environment key.`
						: updated.source === "adc"
							? `${providerLabel(provider.name)} now uses Google Application Default Credentials.`
						: `${providerLabel(provider.name)} API key removed.`,
			});
			await refreshModels().catch(() => {});
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) {
				onForbidden();
			} else {
				setStatus({
					kind: "error",
					text:
						apiErrorDetail(error) ??
						`Could not remove the ${providerLabel(provider.name)} API key.`,
				});
			}
		} finally {
			setPendingProviders((current) => {
				const next = new Set(current);
				next.delete(provider.name);
				return next;
			});
		}
	};

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
			await modelsApi.setModelEnabled(model.provider, model.modelId, isEnabled);
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
			if (isApiError(error) && error.status === 403) {
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
				await modelsApi.setDefaultModel(model.provider, model.modelId);
			} else {
				await modelsApi.clearDefaultModel();
			}
			// Every open model picker preselects the new default without a reload.
			await refreshModels().catch(() => {});
		} catch (error: unknown) {
			// Refetch instead of reverting from a snapshot: the persisted state
			// is the only reliable source after a failure.
			await loadManaged();
			if (isApiError(error) && error.status === 403) {
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
			summary = syncSummary(await modelsApi.syncWhitelist());
		} catch (error: unknown) {
			if (isApiError(error) && error.status === 403) {
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
			const managed = await modelsApi.listManagedModels();
			setModels((current) => preserveManagedModelOrder(current, managed));
			setStatus({ kind: "info", text: summary });
		} catch {
			setStatus({
				kind: "info",
				text: `${summary} The list below could not be refreshed, reload the page.`,
			});
		} finally {
			setIsSyncing(false);
		}
		await refreshModels().catch(() => {});
	};

	return (
		<div>
			<div className="mb-1.5 flex items-baseline gap-2.5">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Workspace models
				</span>
				<span className="text-[10.5px] text-meta dark:text-panel-dim">
					admin
				</span>
				<span className="flex-1" />
				{showSyncControl && (
					<HeaderButton
						accent
						className="gap-1.5 px-3.5 py-[7px] text-[12.5px]"
						disabled={isSyncing}
						onClick={() => {
							void handleSync();
						}}
					>
						<RefreshCw
							className={
								isSyncing ? "size-[13px] animate-spin" : "size-[13px]"
							}
						/>
						Sync catalog
					</HeaderButton>
				)}
			</div>
			<p className="mb-3.5 max-w-[640px] text-[13px] leading-[1.55] text-subtle text-pretty dark:text-panel-body">
				Choose which models members can use in chats and triggers. New catalog
				models start disabled. Star a model to make it the workspace default.
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
			<div className="relative mb-3">
				<Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
				<Input
					type="search"
					value={searchQuery}
					onChange={(event) => {
						setSearchQuery(event.target.value);
					}}
					placeholder="Search models by name"
					aria-label="Search models by name"
					className="h-10 pl-9"
				/>
			</div>

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
						No models match your search.
					</div>
				) : (
					providerGroups.map(
						({ provider, models: providerModels, enabledCount, totalCount }) => (
							<Collapsible
								key={provider.name}
								open={
									searchQuery.trim().length > 0 ||
									openProviders.has(provider.name)
								}
								onOpenChange={(open) => {
									setOpenProviders((current) => {
										const next = new Set(current);
										if (open) next.add(provider.name);
										else next.delete(provider.name);
										return next;
									});
								}}
								className="border-b border-hairline last:border-b-0 dark:border-white/5"
							>
								<CollapsibleTrigger className="group flex w-full cursor-pointer items-center gap-3 bg-sidebar px-4 py-3 text-left transition-colors hover:bg-hover dark:bg-white/[0.03] dark:hover:bg-white/[0.06]">
									<ChevronDown className="size-4 shrink-0 text-faint transition-transform group-data-[state=closed]:-rotate-90" />
									<div className="min-w-0 flex-1">
										<div className="flex items-center gap-2">
											<span className="text-[13.5px] font-semibold text-foreground">
												{providerLabel(provider.name)}
											</span>
											<span
												className={`size-1.5 rounded-full ${
													provider.isConfigured
														? "bg-emerald-500"
														: "bg-faint"
												}`}
											/>
										</div>
										<span className="mt-0.5 block text-[11px] text-meta dark:text-panel-dim">
											{provider.source === "database"
												? `API key configured${
														provider.last4 ? `, ending in ${provider.last4}` : ""
													}`
												: provider.source === "environment"
													? "Using deployment environment key"
													: provider.source === "adc"
														? "Using Google Application Default Credentials"
														: "API key not configured"}
										</span>
									</div>
									<span className="shrink-0 text-[10.5px] text-meta dark:text-panel-dim">
										<span className="font-mono">{enabledCount}/{totalCount}</span> enabled
									</span>
								</CollapsibleTrigger>
								<CollapsibleContent className="data-[state=closed]:animate-collapsible-up data-[state=open]:animate-collapsible-down overflow-hidden">
									<form
										className="flex flex-col gap-2 border-b border-hairline bg-card px-4 py-3 sm:flex-row sm:items-center dark:border-white/5"
										onSubmit={(event) => {
											event.preventDefault();
											void handleProviderKeySave(provider);
										}}
									>
										<Input
											type="password"
											autoComplete="new-password"
											value={keyDrafts[provider.name] ?? ""}
											onChange={(event) => {
												setKeyDrafts((current) => ({
													...current,
													[provider.name]: event.target.value,
												}));
											}}
											placeholder={
												provider.isConfigured
													? "Enter a new API key to replace the current key"
													: "Enter API key"
											}
											aria-label={`${providerLabel(provider.name)} API key`}
											disabled={pendingProviders.has(provider.name)}
											className="h-9 flex-1 font-mono text-[12px]"
										/>
										<div className="flex items-center gap-2">
											<HeaderButton
												type="submit"
												accent
												disabled={
													pendingProviders.has(provider.name) ||
													!(keyDrafts[provider.name]?.trim())
												}
											>
												{pendingProviders.has(provider.name)
													? "Saving…"
													: provider.source === "database"
														? "Replace key"
														: "Save key"}
											</HeaderButton>
											{provider.source === "database" && (
												<button
													type="button"
													aria-label={`Remove ${providerLabel(provider.name)} API key`}
													title="Remove stored API key"
													disabled={pendingProviders.has(provider.name)}
													onClick={() => {
														void handleProviderKeyDelete(provider);
													}}
													className="flex size-8 cursor-pointer items-center justify-center rounded-[7px] text-faint transition-colors hover:bg-destructive/10 hover:text-destructive disabled:cursor-default disabled:opacity-50"
												>
													<Trash2 className="size-3.5" />
												</button>
											)}
										</div>
									</form>
									{providerModels.length === 0 ? (
										<div className="px-4 py-8 text-center text-[13px] text-faint">
											No models available for this provider.
										</div>
									) : (
										providerModels.map((model) => {
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
													<ModelBadge tone="accent">Default</ModelBadge>
												)}
												{model.deprecated && (
													<ModelBadge tone="destructive">
														No longer supported
													</ModelBadge>
												)}
												{model.multimodal && (
													<ModelBadge tone="neutral">Multimodal</ModelBadge>
												)}
												{model.supportsStructuredOutput && (
													<ModelBadge tone="neutral">
														Structured output
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
												!provider.isConfigured ||
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
												(!provider.isConfigured && !model.isEnabled) ||
												(model.deprecated && !model.isEnabled)
											}
											onCheckedChange={(checked) => {
												void handleToggle(model, checked);
											}}
											className="cursor-pointer data-[state=checked]:bg-petrol"
										/>
									</div>
								);
										})
									)}
								</CollapsibleContent>
							</Collapsible>
						),
					)
				)}
			</div>
		</div>
	);
}

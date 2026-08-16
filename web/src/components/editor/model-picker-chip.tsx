"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckIcon, ChevronDown, TriangleAlert } from "lucide-react";
import { cn } from "@/lib/utils";
import { Model } from "@/types/models";
import { useModelsStore } from "@/stores/models-store";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import { SearchBar } from "@/components/ui/search-bar";
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogTrigger,
} from "@/components/ui/dialog";

interface ModelPickerChipProps {
	value: string | null;
	onChange: (modelId: string) => void;
	/** Read-only chip: no dialog. */
	disabled?: boolean;
	/** Label for a `value` that is not in the available models list (e.g. the
	 * whitelist display name of an admin-disabled model). Falls back to the
	 * raw `value`. */
	unavailableLabel?: string | null;
	/** Authoritative unavailability (e.g. the server-computed
	 * `model_available` flag). When provided it overrides the catalog-derived
	 * inference, which is only a fallback (wrong while the catalog is loading
	 * and unknowable if its fetch failed). */
	unavailable?: boolean;
}

/** Small pill showing the selected model; opens the model catalog dialog. */
export function ModelPickerChip({
	value,
	onChange,
	disabled,
	unavailableLabel,
	unavailable,
}: ModelPickerChipProps) {
	const models = useModelsStore((state) => state.models);
	const isCatalogLoaded = useModelsStore((state) => state.isInitialized);
	const fetchModels = useModelsStore((state) => state.fetchModels);
	const [open, setOpen] = useState(false);
	const [search, setSearch] = useState("");

	useEffect(() => {
		fetchModels().catch(() => {
			// surfaced by the store; the chip just shows the placeholder
		});
	}, [fetchModels]);

	const selected = models.find((model) => model.id === value);
	// Explicit server flag wins; otherwise infer from catalog membership, but
	// only once the catalog actually loaded (no false warning during load).
	const showAsUnavailable =
		value != null && (unavailable ?? (isCatalogLoaded && !selected));

	const groupedModels = useMemo(() => {
		const q = search.trim().toLowerCase();
		const filtered = q
			? models.filter(
					(m) =>
						m.name.toLowerCase().includes(q) ||
						m.chef.toLowerCase().includes(q),
				)
			: models;
		return filtered.reduce(
			(acc, model) => {
				acc[model.chef] = acc[model.chef] || [];
				acc[model.chef].push(model);
				return acc;
			},
			{} as Record<string, Model[]>,
		);
	}, [models, search]);

	const hasResults = Object.keys(groupedModels).length > 0;

	const handleOpenChange = (nextOpen: boolean) => {
		setOpen(nextOpen);
		if (!nextOpen) setSearch("");
	};

	const chip = (
		<div
			className={cn(
				"inline-flex items-center gap-2 h-9 rounded-full px-3 bg-hover dark:bg-white/5 text-[13px] font-medium text-foreground transition-colors",
				!disabled &&
					"cursor-pointer hover:bg-petrol-tint dark:hover:bg-white/10",
			)}
		>
			{selected && !showAsUnavailable ? (
				<>
					<ModelSelectorLogo provider={selected.chefSlug} className="size-3" />
					<span className="truncate">{selected.name}</span>
				</>
			) : showAsUnavailable ? (
				// Bound to a model that is no longer offered (removed from the
				// catalog or disabled by an admin). Keep the binding visible —
				// a blank "Select model" would read as "not set".
				<span className="inline-flex items-center gap-1.5 text-warning dark:text-amber-400">
					<TriangleAlert className="size-3 shrink-0" />
					<span className="truncate">{unavailableLabel ?? value}</span>
					<span className="font-normal">· unavailable</span>
				</span>
			) : value ? (
				<span className="truncate">{unavailableLabel ?? value}</span>
			) : (
				<span className="text-meta dark:text-white/40">Select model</span>
			)}
			{!disabled && (
				<ChevronDown className="size-[15px] shrink-0 text-faint" />
			)}
		</div>
	);

	if (disabled) {
		return chip;
	}

	return (
		<Dialog open={open} onOpenChange={handleOpenChange}>
			<DialogTrigger asChild>
				<button type="button">{chip}</button>
			</DialogTrigger>
			<DialogContent className="gap-0 p-0">
				<div className="px-6 pt-6 pb-4">
					<DialogTitle className="text-[16px] leading-snug font-bold text-ink dark:text-panel-button">
						Select a model
					</DialogTitle>
					<p className="mt-1.5 text-[13px] leading-[1.5] text-label dark:text-panel-dim">
						Choose the model running the instructions
					</p>
				</div>

				<div className="px-6 pb-3">
					<SearchBar
						placeholder="Search models..."
						value={search}
						onChange={setSearch}
					/>
				</div>

				<div className="px-4 pb-5 max-h-[55vh] overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{!hasResults ? (
						<div className="px-4 py-8 text-center text-[13px] text-faint dark:text-muted-foreground">
							No models found.
						</div>
					) : (
						Object.entries(groupedModels).map(([chefName, chefModels]) => (
							<div key={chefName} className="px-2 pt-2">
								<div className="px-3 pb-1.5 font-mono text-[10.5px] font-semibold uppercase tracking-[0.09em] text-meta dark:text-panel-dim">
									{chefName}
								</div>
								<div className="flex flex-col gap-0.5">
									{chefModels.map((model) => {
										const isActive = value === model.id;
										return (
											<button
												key={model.id}
												type="button"
												onClick={() => {
													onChange(model.id);
													handleOpenChange(false);
												}}
												className={cn(
													"flex w-full items-center gap-3 px-3 py-2.5 rounded-[10px] cursor-pointer transition-colors text-left outline-none",
													"text-[14px] font-medium",
													isActive
														? "bg-petrol-tint dark:bg-white/5 text-foreground"
														: "text-foreground hover:bg-hover dark:hover:bg-white/5",
												)}
											>
												<ModelSelectorLogo provider={model.chefSlug} />
												<span className="flex-1 truncate">{model.name}</span>
												{isActive && (
													<CheckIcon
														className="ml-auto size-4 shrink-0 text-petrol dark:text-panel-terminal"
														strokeWidth={3}
													/>
												)}
											</button>
										);
									})}
								</div>
							</div>
						))
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}

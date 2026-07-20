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
}

/** Small pill showing the selected model; opens the model catalog dialog. */
export function ModelPickerChip({
	value,
	onChange,
	disabled,
	unavailableLabel,
}: ModelPickerChipProps) {
	const models = useModelsStore((state) => state.models);
	const fetchModels = useModelsStore((state) => state.fetchModels);
	const [open, setOpen] = useState(false);
	const [search, setSearch] = useState("");

	useEffect(() => {
		fetchModels().catch(() => {
			// surfaced by the store; the chip just shows the placeholder
		});
	}, [fetchModels]);

	const selected = models.find((model) => model.id === value);

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
				"inline-flex items-center gap-2 h-9 rounded-full px-3 bg-[#F5F8F6] dark:bg-white/5 font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#1E2D28] dark:text-white transition-colors",
				!disabled &&
					"cursor-pointer hover:bg-[#EDF4F0] dark:hover:bg-white/10",
			)}
		>
			{selected ? (
				<>
					<ModelSelectorLogo provider={selected.chefSlug} className="size-3" />
					<span className="truncate">{selected.name}</span>
				</>
			) : value ? (
				// Bound to a model that is no longer offered (removed from the
				// catalog or disabled by an admin). Keep the binding visible —
				// a blank "Select model" would read as "not set".
				<span className="inline-flex items-center gap-1.5 text-[#B4643C] dark:text-amber-400">
					<TriangleAlert className="size-3 shrink-0" />
					<span className="truncate">{unavailableLabel ?? value}</span>
					<span className="font-normal">· unavailable</span>
				</span>
			) : (
				<span className="text-[#8FA89E] dark:text-white/40">Select model</span>
			)}
			{!disabled && (
				<ChevronDown className="size-[15px] shrink-0 text-[#7C8C84]" />
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
			<DialogContent
				className="sm:max-w-[480px] rounded-[28px] p-0 gap-0 overflow-hidden"
				showCloseButton={false}
			>
				<div className="flex items-start justify-between px-7 pt-6 pb-4">
					<div>
						<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[20px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
							Select a model
						</DialogTitle>
						<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-1">
							Choose the model running the instructions
						</p>
					</div>
				</div>

				<div className="px-7 pb-3">
					<SearchBar
						placeholder="Search models..."
						value={search}
						onChange={setSearch}
					/>
				</div>

				<div className="px-4 pb-5 max-h-[55vh] overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					{!hasResults ? (
						<div className="font-[family-name:var(--font-dm-sans)] px-4 py-8 text-center text-[13px] text-[#A3B5AD] dark:text-muted-foreground">
							No models found.
						</div>
					) : (
						Object.entries(groupedModels).map(([chefName, chefModels]) => (
							<div key={chefName} className="px-2 pt-2">
								<div className="font-[family-name:var(--font-dm-sans)] px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#8FA89E] dark:text-muted-foreground">
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
													"flex w-full items-center gap-3 px-3 py-2.5 rounded-[14px] cursor-pointer transition-colors text-left outline-none",
													"font-[family-name:var(--font-dm-sans)] text-[14px] font-medium",
													isActive
														? "bg-[#F8FAF9] dark:bg-white/5 text-[#1E2D28] dark:text-white"
														: "text-[#1E2D28] dark:text-white/90 hover:bg-[#F8FAF9] dark:hover:bg-white/5",
												)}
											>
												<ModelSelectorLogo provider={model.chefSlug} />
												<span className="flex-1 truncate">{model.name}</span>
												{isActive && (
													<CheckIcon
														className="ml-auto size-4 shrink-0 text-[#4CA882]"
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

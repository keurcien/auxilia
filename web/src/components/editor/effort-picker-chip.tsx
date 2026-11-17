"use client";

import { Brain, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { effortLabel } from "@/lib/reasoning-effort";
import { useModelsStore } from "@/stores/models-store";
import { DropdownMenu } from "@/components/ui/dropdown-menu";

interface EffortPickerChipProps {
	modelId: string | null;
	/** Stored effort; null = the model's default. */
	value: string | null;
	onChange?: (effort: string | null) => void;
	/** Read-only chip: no menu. */
	disabled?: boolean;
}

/** Reasoning-effort pill for a model; hidden when the model has no effort knob. */
export function EffortPickerChip({
	modelId,
	value,
	onChange,
	disabled,
}: EffortPickerChipProps) {
	const model = useModelsStore((state) =>
		state.models.find((candidate) => candidate.id === modelId),
	);
	const levels = model?.reasoningEffortLevels ?? [];
	const modelDefault = model?.reasoningEffortDefault ?? null;
	// A stored effort the catalog no longer declares falls back to the default.
	const effective =
		value && (model === undefined || levels.includes(value)) ? value : null;

	if (levels.length === 0 && !effective) return null;

	const label = effective
		? effortLabel(effective)
		: modelDefault
			? `Default (${effortLabel(modelDefault)})`
			: "Auto";

	const chip = (
		<span
			className={cn(
				"inline-flex h-9 items-center gap-1.5 rounded-full bg-hover px-3 text-[13px] font-medium text-foreground transition-colors dark:bg-white/5",
				!disabled &&
					"cursor-pointer hover:bg-petrol-tint dark:hover:bg-white/10",
			)}
		>
			<Brain className="size-3.5 shrink-0 text-meta dark:text-panel-dim" />
			<span className="truncate">{label}</span>
			{!disabled && <ChevronDown className="size-[15px] shrink-0 text-faint" />}
		</span>
	);

	if (disabled || !onChange || levels.length === 0) return chip;

	return (
		<DropdownMenu
			align="start"
			className="[&_[role=menuitem]+[role=menuitem]]:mt-0.5"
			items={[
				{ sectionLabel: "Reasoning effort" },
				{
					label: modelDefault
						? `Default (${effortLabel(modelDefault)})`
						: "Auto",
					active: !effective,
					onClick: () => {
						onChange(null);
					},
				},
				...levels.map((level) => ({
					label: effortLabel(level),
					active: effective === level,
					onClick: () => {
						onChange(level);
					},
				})),
			]}
			trigger={
				<button type="button" aria-label="Reasoning effort">
					{chip}
				</button>
			}
		/>
	);
}

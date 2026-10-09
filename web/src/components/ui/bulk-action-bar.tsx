"use client";

import { Trash2, X } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

interface BulkActionBarProps {
	selectedCount: number;
	totalCount: number;
	allSelected: boolean;
	someSelected: boolean;
	onToggleAll: () => void;
	onClear: () => void;
	actionLabel: string;
	onAction: () => void;
	showWhenEmpty?: boolean;
	actionIcon?: React.ReactNode;
	className?: string;
}

export function BulkActionBar({
	selectedCount,
	totalCount,
	allSelected,
	someSelected,
	onToggleAll,
	onClear,
	actionLabel,
	onAction,
	showWhenEmpty = false,
	actionIcon = <Trash2 className="size-3.5" />,
	className,
}: BulkActionBarProps) {
	if (selectedCount === 0) {
		if (!showWhenEmpty || totalCount === 0) return null;
		return (
			<div className={cn("mb-3 flex items-center gap-2 px-1", className)}>
				<Checkbox
					checked={false}
					aria-label={`Select all ${totalCount} items`}
					onCheckedChange={onToggleAll}
				/>
				<button
					type="button"
					onClick={onToggleAll}
					className="cursor-pointer text-[11.5px] font-medium text-meta transition-colors hover:text-petrol dark:text-panel-dim dark:hover:text-panel-terminal"
				>
					Select all
				</button>
				<span className="font-mono text-[10.5px] text-ghost">{totalCount}</span>
			</div>
		);
	}

	return (
		<div
			className={cn(
				"mb-3 flex min-h-11 animate-in flex-wrap items-center gap-2 rounded-[11px] border border-border bg-sidebar px-3 py-2 fade-in slide-in-from-top-1 dark:border-white/10 dark:bg-[#182125]",
				className,
			)}
		>
			<Checkbox
				checked={allSelected ? true : someSelected ? "indeterminate" : false}
				aria-label={allSelected ? "Unselect all" : "Select all"}
				onCheckedChange={onToggleAll}
			/>
			<span className="text-[11.5px] font-semibold text-petrol dark:text-panel-terminal">
				{selectedCount} selected
			</span>
			<button
				type="button"
				onClick={onClear}
				className="ml-1 inline-flex cursor-pointer items-center gap-1 text-[11.5px] font-medium text-meta transition-colors hover:text-foreground dark:text-panel-dim"
			>
				<X className="size-3" />
				Clear
			</button>
			<button
				type="button"
				onClick={onAction}
				className="ml-auto inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-[#B04A3A] px-3 py-1.5 text-[11.5px] font-semibold text-white shadow-[0_1px_2px_rgba(105,38,28,0.2)] transition-[background-color,transform] hover:bg-[#9E4032] active:translate-y-px"
			>
				{actionIcon}
				{actionLabel}
			</button>
		</div>
	);
}

"use client";

import { Trash2, X } from "lucide-react";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

export interface BulkAction {
	label: string;
	icon?: React.ReactNode;
	onClick: () => void;
	destructive?: boolean;
}

interface BulkActionBarProps {
	selectedCount: number;
	totalCount: number;
	allSelected: boolean;
	someSelected: boolean;
	onToggleAll: () => void;
	onClear: () => void;
	/** Single destructive action; ignored when `actions` is given. */
	actionLabel?: string;
	onAction?: () => void;
	actionIcon?: React.ReactNode;
	/** Several actions, in display order. */
	actions?: BulkAction[];
	/** Overflow menu rendered before the actions. */
	menu?: React.ReactNode;
	/** Disables the actions while one runs. */
	busy?: boolean;
	showWhenEmpty?: boolean;
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
	actionIcon = <Trash2 className="size-3.5" />,
	actions,
	menu,
	busy = false,
	showWhenEmpty = false,
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

	const items: BulkAction[] =
		actions ??
		(actionLabel && onAction
			? [{ label: actionLabel, icon: actionIcon, onClick: onAction, destructive: true }]
			: []);

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
			<div className="ml-auto flex flex-wrap items-center justify-end gap-2">
				{menu}
				{items.map((action) => (
					<button
						key={action.label}
						type="button"
						disabled={busy}
						onClick={action.onClick}
						className={cn(
							"inline-flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] px-3 py-1.5 text-[11.5px] font-semibold transition-[background-color,border-color,transform] active:translate-y-px disabled:cursor-default disabled:opacity-50 disabled:active:translate-y-0 [&_svg]:size-3.5",
							action.destructive
								? "bg-[#B04A3A] text-white shadow-[0_1px_2px_rgba(105,38,28,0.2)] hover:bg-[#9E4032]"
								: "border border-border bg-card text-foreground hover:border-border-hover dark:border-white/10 dark:hover:border-white/20",
						)}
					>
						{action.icon}
						{action.label}
					</button>
				))}
			</div>
		</div>
	);
}

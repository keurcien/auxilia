"use client";

import { LayoutGrid, List } from "lucide-react";
import { cn } from "@/lib/utils";

export type ViewMode = "table" | "cards";

interface ViewToggleProps {
	value: ViewMode;
	onChange: (mode: ViewMode) => void;
	className?: string;
}

/** Petrol Mono ☰/▦ view toggle: bordered 6px segments, active on the tint. */
export function ViewToggle({ value, onChange, className }: ViewToggleProps) {
	const segments: { mode: ViewMode; icon: React.ReactNode; label: string }[] = [
		{ mode: "table", icon: <List className="size-[13px]" />, label: "Table view" },
		{ mode: "cards", icon: <LayoutGrid className="size-[13px]" />, label: "Card view" },
	];

	return (
		<span
			className={cn(
				"inline-flex shrink-0 overflow-hidden rounded-[6px] border border-border",
				className,
			)}
		>
			{segments.map(({ mode, icon, label }) => (
				<button
					key={mode}
					type="button"
					title={label}
					aria-label={label}
					aria-pressed={value === mode}
					onClick={() => {
						onChange(mode);
					}}
					className={cn(
						"flex cursor-pointer items-center justify-center px-2.5 py-[7px] transition-colors",
						value === mode
							? "bg-petrol-tint text-foreground dark:bg-white/10"
							: "text-meta hover:text-foreground dark:text-panel-dim",
					)}
				>
					{icon}
				</button>
			))}
		</span>
	);
}

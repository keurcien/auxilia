"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

interface SelectableLeadingProps {
	children: React.ReactNode;
	selected: boolean;
	selectionMode: boolean;
	onToggle: (shiftKey: boolean) => void;
	label: string;
	disabled?: boolean;
	className?: string;
}

export function SelectableLeading({
	children,
	selected,
	selectionMode,
	onToggle,
	label,
	disabled = false,
	className,
}: SelectableLeadingProps) {
	if (disabled) {
		return <span className={cn("shrink-0", className)}>{children}</span>;
	}

	return (
		<span className={cn("relative grid shrink-0 place-items-center", className)}>
			<span
				aria-hidden={selectionMode || undefined}
				className={cn(
					"col-start-1 row-start-1 transition-[opacity,transform] duration-150",
					selectionMode
						? "scale-90 opacity-0"
						: "opacity-100 group-hover:scale-90 group-hover:opacity-0",
				)}
			>
				{children}
			</span>
			<span
				className={cn(
					"col-start-1 row-start-1 transition-[opacity,transform] duration-150",
					selectionMode
						? "scale-100 opacity-100"
						: "pointer-events-none scale-90 opacity-0 group-hover:pointer-events-auto group-hover:scale-100 group-hover:opacity-100 focus-within:pointer-events-auto focus-within:scale-100 focus-within:opacity-100",
				)}
			>
				<Checkbox
					checked={selected}
					aria-label={label}
					onCheckedChange={(_checked, event) => {
						onToggle(event.shiftKey);
					}}
				/>
			</span>
		</span>
	);
}

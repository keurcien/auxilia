"use client";

import { Check, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

export type CheckboxState = boolean | "indeterminate";

interface CheckboxProps {
	checked: CheckboxState;
	onCheckedChange: (
		checked: boolean,
		event: React.MouseEvent<HTMLButtonElement>,
	) => void;
	disabled?: boolean;
	"aria-label": string;
	className?: string;
}

export function Checkbox({
	checked,
	onCheckedChange,
	disabled = false,
	"aria-label": ariaLabel,
	className,
}: CheckboxProps) {
	const active = checked === true || checked === "indeterminate";

	return (
		<button
			type="button"
			role="checkbox"
			aria-label={ariaLabel}
			aria-checked={checked === "indeterminate" ? "mixed" : checked}
			disabled={disabled}
			onClick={(event) => {
				event.preventDefault();
				event.stopPropagation();
				onCheckedChange(checked !== true, event);
			}}
			className={cn(
				"flex size-[18px] shrink-0 cursor-pointer items-center justify-center rounded-[5px] border transition-[background-color,border-color,box-shadow,transform] duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/25 focus-visible:ring-offset-2 active:scale-95 disabled:cursor-not-allowed disabled:opacity-35",
				active
					? "border-petrol bg-petrol text-white shadow-[0_1px_2px_rgba(25,87,67,0.22)]"
					: "border-[#B9CAC2] bg-card text-transparent hover:border-petrol/70 dark:border-white/25 dark:bg-[#162025]",
				className,
			)}
		>
			{checked === "indeterminate" ? (
				<Minus className="size-3" strokeWidth={2.5} />
			) : (
				<Check
					className={cn("size-3 transition-opacity", checked ? "opacity-100" : "opacity-0")}
					strokeWidth={2.5}
				/>
			)}
		</button>
	);
}

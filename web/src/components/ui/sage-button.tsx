import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cn } from "@/lib/utils";

interface SageButtonProps extends React.ComponentProps<"button"> {
	color?: "dark" | "outline" | "ghost" | "destructive-ghost";
	asChild?: boolean;
}

export function SageButton({
	className,
	color = "dark",
	asChild = false,
	...props
}: SageButtonProps) {
	const Comp = asChild ? Slot : "button";

	return (
		<Comp
			className={cn(
				"inline-flex items-center justify-center gap-2 px-5.5 py-2.5 rounded-full font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold cursor-pointer transition-all disabled:opacity-50 disabled:cursor-not-allowed [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
				color === "dark" &&
					"bg-[#111111] dark:bg-white text-white dark:text-[#111111] shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] hover:opacity-90",
				color === "outline" &&
					"border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent text-[#1E2D28] dark:text-foreground hover:border-[#A3B5AD]",
				color === "ghost" &&
					"bg-transparent text-[#6B7F76] dark:text-muted-foreground hover:bg-[#F5F8F6] dark:hover:bg-white/5",
				color === "destructive-ghost" &&
					"bg-transparent text-[#D45B45] hover:bg-[#FFF5F3] dark:hover:bg-[#D45B45]/10",
				className,
			)}
			{...props}
		/>
	);
}

import * as React from "react";
import { cn } from "@/lib/utils";

interface SageInputProps extends React.ComponentProps<"input"> {
	error?: boolean;
}

export function SageInput({ className, error, ...props }: SageInputProps) {
	return (
		<input
			className={cn(
				"w-full px-[18px] py-3 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-white placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 outline-none focus:border-[#4CA882] transition-colors",
				error && "border-[#D45B45] focus:border-[#D45B45]",
				className,
			)}
			{...props}
		/>
	);
}

interface SageTextareaProps extends React.ComponentProps<"textarea"> {
	error?: boolean;
}

export function SageTextarea({
	className,
	error,
	...props
}: SageTextareaProps) {
	return (
		<textarea
			className={cn(
				"w-full px-[18px] py-3 rounded-[20px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 font-[family-name:var(--font-dm-sans)] text-[14px] font-medium text-[#1E2D28] dark:text-white leading-relaxed placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 outline-none focus:border-[#4CA882] transition-colors resize-vertical",
				error && "border-[#D45B45] focus:border-[#D45B45]",
				className,
			)}
			{...props}
		/>
	);
}

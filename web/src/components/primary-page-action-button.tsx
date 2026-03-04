import type { ComponentProps } from "react";
import type { LucideIcon } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface PrimaryPageActionButtonProps
	extends Omit<ComponentProps<typeof Button>, "children"> {
	icon: LucideIcon;
	label: string;
	isLoading?: boolean;
	loadingLabel?: string;
}

export function PrimaryPageActionButton({
	icon: Icon,
	label,
	isLoading = false,
	loadingLabel,
	disabled,
	className,
	...props
}: PrimaryPageActionButtonProps) {
	return (
		<Button
			className={cn(
				"flex cursor-pointer items-center gap-2 rounded-[14px] border-none bg-[#2A2F2D] py-2.5 text-sm font-semibold text-white shadow-[0_4px_14px_rgba(118,181,160,0.14)] transition-colors hover:bg-[#363D3A] md:py-5 md:text-base",
				className,
			)}
			disabled={disabled || isLoading}
			{...props}
		>
			<Icon className="h-4 w-4" />
			{isLoading && loadingLabel ? loadingLabel : label}
		</Button>
	);
}

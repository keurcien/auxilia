"use client";

import * as React from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { cn } from "@/lib/utils";

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverClose = PopoverPrimitive.Close;

export function PopoverContent({
	className,
	align = "end",
	sideOffset = 6,
	...props
}: React.ComponentProps<typeof PopoverPrimitive.Content>) {
	return (
		<PopoverPrimitive.Portal>
			<PopoverPrimitive.Content
				align={align}
				sideOffset={sideOffset}
				collisionPadding={12}
				className={cn(
					"z-50 rounded-[12px] border border-hairline bg-canvas shadow-[0_12px_32px_-12px_rgba(10,25,30,0.18)] outline-none dark:border-white/10 dark:bg-card",
					"data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-1",
					"data-[state=closed]:animate-out data-[state=closed]:fade-out-0",
					className,
				)}
				{...props}
			/>
		</PopoverPrimitive.Portal>
	);
}

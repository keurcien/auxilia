"use client";

import { Toaster as Sonner } from "sonner";

/**
 * App-wide toaster, styled to the Petrol Mono kit: white card, hairline
 * border, ink text, petrol icon — no pill radii, no colored fills.
 */
export function Toaster() {
	return (
		<Sonner
			position="bottom-right"
			gap={10}
			toastOptions={{
				unstyled: true,
				classNames: {
					toast:
						"flex w-[356px] items-center gap-2.5 rounded-[10px] border border-hairline bg-card px-4 py-3 text-[13px] font-semibold text-foreground shadow-[0_16px_40px_-14px_rgba(10,25,30,0.28)] dark:border-white/10",
					icon: "shrink-0 text-petrol [&_svg]:size-4",
					title: "font-semibold",
					description: "text-[12px] font-normal text-subtle",
				},
			}}
		/>
	);
}

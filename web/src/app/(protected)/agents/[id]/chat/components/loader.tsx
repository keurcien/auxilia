"use client";

import { cn } from "@/lib/utils";
import { Shimmer } from "@/components/ai-elements/shimmer";
import type { HTMLAttributes } from "react";

export type LoaderProps = HTMLAttributes<HTMLDivElement>;

export const ThinkingLoader = ({ className, ...props }: LoaderProps) => (
	<div className={cn("flex items-center p-2", className)} {...props}>
		<Shimmer as="span" className="text-md">
			Thinking...
		</Shimmer>
	</div>
);

export const DotsLoader = ({ className, ...props }: LoaderProps) => (
	<div className={cn("flex items-center gap-1 p-2", className)} {...props}>
		{[0, 1, 2].map((i) => (
			<div
				key={i}
				className="h-1.5 w-1.5 rounded-full bg-muted-foreground animate-[dot-pulse_1.4s_ease-in-out_infinite]"
				style={{ animationDelay: `${i * 0.2}s` }}
			/>
		))}
	</div>
);

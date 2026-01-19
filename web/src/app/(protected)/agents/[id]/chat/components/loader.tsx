import { cn } from "@/lib/utils";
import type { HTMLAttributes } from "react";

export type LoaderProps = HTMLAttributes<HTMLDivElement>;

export const Loader = ({ className, ...props }: LoaderProps) => (
	<div className={cn("flex items-center space-x-1 p-2", className)} {...props}>
		<div className="flex space-x-1">
			<div
				className="h-2 w-2 bg-gray-500 dark:bg-gray-400 rounded-full animate-bounce"
				style={{ animationDelay: "0ms" }}
			/>
			<div
				className="h-2 w-2 bg-gray-500 dark:bg-gray-400 rounded-full animate-bounce"
				style={{ animationDelay: "150ms" }}
			/>
			<div
				className="h-2 w-2 bg-gray-500 dark:bg-gray-400 rounded-full animate-bounce"
				style={{ animationDelay: "300ms" }}
			/>
		</div>
	</div>
);

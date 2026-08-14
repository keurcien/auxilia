"use client";

import { cn } from "@/lib/utils";

export interface UnderlineTab<K extends string> {
	key: K;
	label: string;
	count?: number;
}

interface UnderlineTabsProps<K extends string> {
	tabs: readonly UnderlineTab<K>[];
	value: K;
	onChange: (key: K) => void;
	className?: string;
}

/**
 * Petrol Mono underline tabs: active = ink w600 + 2px petrol underline,
 * counts in mono (petrol when active). Used for page sections and view
 * filters in workspace page headers.
 */
export function UnderlineTabs<K extends string>({
	tabs,
	value,
	onChange,
	className,
}: UnderlineTabsProps<K>) {
	return (
		<div className={cn("flex gap-0.5", className)}>
			{tabs.map((tab) => {
				const active = tab.key === value;
				return (
					<button
						key={tab.key}
						type="button"
						onClick={() => {
							onChange(tab.key);
						}}
						className={cn(
							"cursor-pointer border-b-2 px-3 py-2 text-[13px] transition-colors",
							active
								? "border-petrol font-semibold text-foreground"
								: "border-transparent font-medium text-muted-foreground hover:text-foreground",
						)}
					>
						{tab.label}
						{tab.count !== undefined && (
							<span
								className={cn(
									"ml-1.5 font-mono text-[10.5px]",
									active ? "text-petrol" : "text-meta dark:text-panel-dim",
								)}
							>
								{tab.count}
							</span>
						)}
					</button>
				);
			})}
		</div>
	);
}

"use client";

import { cn } from "@/lib/utils";

export interface UnderlineTab<K extends string> {
	key: K;
	label: string;
	count?: number;
	alert?: string;
}

interface UnderlineTabsProps<K extends string> {
	tabs: readonly UnderlineTab<K>[];
	value: K;
	onChange: (key: K) => void;
	className?: string;
	idPrefix?: string;
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
	idPrefix,
}: UnderlineTabsProps<K>) {
	return (
		<div
			role="tablist"
			className={cn(
				"flex min-w-0 gap-0.5 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
				className,
			)}
		>
			{tabs.map((tab) => {
				const active = tab.key === value;
				return (
					<button
						key={tab.key}
						type="button"
						role="tab"
						id={idPrefix ? `${idPrefix}-tab-${tab.key}` : undefined}
						aria-controls={
							idPrefix ? `${idPrefix}-panel-${tab.key}` : undefined
						}
						aria-selected={active}
						tabIndex={active ? 0 : -1}
						onClick={() => {
							onChange(tab.key);
						}}
						onKeyDown={(event) => {
							if (
								!["ArrowLeft", "ArrowRight", "Home", "End"].includes(
									event.key,
								)
							) {
								return;
							}
							event.preventDefault();
							const currentIndex = tabs.findIndex(
								(candidate) => candidate.key === tab.key,
							);
							const nextIndex =
								event.key === "Home"
									? 0
									: event.key === "End"
										? tabs.length - 1
										: event.key === "ArrowRight"
											? (currentIndex + 1) % tabs.length
											: (currentIndex - 1 + tabs.length) % tabs.length;
							const next = tabs[nextIndex];
							if (!next) return;
							onChange(next.key);
							const tablist = event.currentTarget.parentElement;
							const buttons =
								tablist?.querySelectorAll<HTMLButtonElement>('[role="tab"]');
							buttons?.item(nextIndex).focus();
						}}
						className={cn(
							"shrink-0 cursor-pointer whitespace-nowrap border-b-2 px-3 py-2 text-[13px] transition-colors",
							active
								? "border-petrol font-semibold text-foreground"
								: "border-transparent font-medium text-muted-foreground hover:text-foreground",
						)}
					>
						{tab.label}
						{tab.alert && (
							<span
								title={tab.alert}
								role="img"
								aria-label={tab.alert}
								className="ml-1.5 inline-block size-1.5 rounded-full bg-warning align-middle"
							/>
						)}
						{tab.count !== undefined && (
							<span
								className={cn(
									"ml-1.5 font-mono text-[10.5px]",
									active
										? "text-petrol dark:text-panel-terminal"
										: "text-meta dark:text-panel-dim",
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

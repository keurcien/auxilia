"use client";

import { ChevronsDownUp, ChevronsUpDown } from "lucide-react";
import { setGroupsExpanded, useAllGroupsExpanded } from "@/lib/group-expansion";
import { cn } from "@/lib/utils";

/** "Collapse all" / "Expand all" control for the group sections of a view. */
export function GroupExpansionToggle({
	storageKeys,
	className,
}: {
	storageKeys: string[];
	className?: string;
}) {
	const allExpanded = useAllGroupsExpanded(storageKeys);
	const Icon = allExpanded ? ChevronsDownUp : ChevronsUpDown;

	return (
		<div className={cn("flex shrink-0 justify-end", className)}>
			<button
				type="button"
				onClick={() => {
					setGroupsExpanded(storageKeys, !allExpanded);
				}}
				className="flex cursor-pointer items-center gap-1.5 rounded-[6px] px-2 py-1 text-[11.5px] font-medium text-meta transition-colors hover:bg-sidebar hover:text-foreground dark:text-panel-dim dark:hover:bg-white/5"
			>
				<Icon className="size-3.5" />
				{allExpanded ? "Collapse all" : "Expand all"}
			</button>
		</div>
	);
}

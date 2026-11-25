import Link from "next/link";
import { cn } from "@/lib/utils";

/**
 * Compact outline link for a table row's actions (Edit, Open, Chat…). A real
 * link, so middle-click and Cmd/Ctrl+click open it in a new tab; place it in a
 * cell that stops click propagation when the row itself is clickable.
 */
export function RowActionLink({
	className,
	...props
}: React.ComponentProps<typeof Link>) {
	return (
		<Link
			className={cn(
				"cursor-pointer whitespace-nowrap rounded-[7px] border border-border px-[11px] py-[5px] text-[12px] font-medium text-body transition-colors hover:bg-sidebar dark:text-panel-body dark:hover:bg-white/5",
				className,
			)}
			{...props}
		/>
	);
}

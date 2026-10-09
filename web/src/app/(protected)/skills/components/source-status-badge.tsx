import { cn } from "@/lib/utils";
import type { SkillSourceStatus } from "@/types/skills";

/**
 * The last sync's outcome as a mono-caps chip. "Not configured" (auth),
 * "permanently broken" (not found / invalid), "nothing pushed yet" (empty)
 * and "temporarily unavailable" never share a label — the API tells them
 * apart by type, the badge by copy. An empty repository used to read as
 * UNREACHABLE, which pointed at the network instead of at the repository.
 */
function badgeFor(status: SkillSourceStatus | null): { label: string; className: string } {
	switch (status) {
		case "ok":
			return { label: "Synced", className: "bg-success-bg text-success dark:bg-emerald-950 dark:text-emerald-300" };
		case "auth":
			return { label: "Needs a token", className: "bg-warning-bg text-warning" };
		case "empty":
			return { label: "Empty", className: "bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body" };
		case "unavailable":
			return { label: "Unreachable", className: "bg-warning-bg text-warning" };
		case "not_found":
			return { label: "Not found", className: "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/15" };
		case "invalid":
			return { label: "Invalid", className: "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/15" };
		case null:
			return { label: "Never synced", className: "bg-neutral-bg text-subtle dark:bg-white/10 dark:text-panel-body" };
	}
}

export function SourceStatusBadge({
	status,
	title,
	className,
}: {
	status: SkillSourceStatus | null;
	title?: string | null;
	className?: string;
}) {
	const badge = badgeFor(status);
	return (
		<span
			title={title ?? undefined}
			className={cn(
				"inline-flex shrink-0 items-center whitespace-nowrap rounded-[4px] px-2 py-[3px] text-[9.5px] font-semibold ",
				badge.className,
				className,
			)}
		>
			{badge.label}
		</span>
	);
}

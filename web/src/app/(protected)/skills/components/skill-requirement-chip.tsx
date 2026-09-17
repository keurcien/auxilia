import { cn } from "@/lib/utils";

/**
 * What a skill needs from the agent it's enabled on — the one thing a
 * reader has to know when attaching it. One noun ("skill") everywhere; the
 * chip states the requirement instead of a type: a skill without scripts
 * runs on any agent, a skill with scripts needs one that runs code (its
 * instructions still apply either way). Mono 9.5/600 pill, design 23c.
 */
export function SkillRequirementChip({
	scriptCount,
	className,
}: {
	scriptCount: number;
	className?: string;
}) {
	const needsCode = scriptCount > 0;
	return (
		<span
			className={cn(
				"inline-flex shrink-0 items-center whitespace-nowrap rounded-full px-[9px] py-[3px] font-mono text-[9.5px] font-semibold",
				needsCode
					? "bg-petrol text-white"
					: "bg-hover text-subtle dark:bg-white/10 dark:text-panel-body",
				className,
			)}
		>
			{needsCode
				? `needs code execution · ${scriptCount} script${scriptCount === 1 ? "" : "s"}`
				: "runs anywhere"}
		</span>
	);
}

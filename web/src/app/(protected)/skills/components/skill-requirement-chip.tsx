import { cn } from "@/lib/utils";

/**
 * What a skill needs from the agent it's enabled on.
 *
 * Only the *constraint* is badged. A skill without scripts runs on any
 * agent, which is the ordinary case — badging it too put two similar chips
 * side by side and left a reader comparing wording to tell them apart, so
 * the plain case renders nothing and presence alone carries the meaning.
 * Callers that need to say something in the empty case (a table column) say
 * it in their own words.
 *
 * Same shape as every other badge in the workspace (UPDATE, GONE UPSTREAM,
 * SCRIPT): a tinted rectangle in mono caps, not a filled pill. The column
 * header or the file list supplies the verb, so the badge only has to name
 * the thing; the title carries the full sentence for anyone who stops on it.
 */
export function SkillRequirementChip({
	scriptCount,
	className,
}: {
	scriptCount: number;
	className?: string;
}) {
	if (scriptCount === 0) return null;
	return (
		<span
			title={`This skill runs ${scriptCount} script${
				scriptCount === 1 ? "" : "s"
			} — its instructions apply on any agent, but the scripts only run on one with code execution.`}
			className={cn(
				"shrink-0 whitespace-nowrap rounded-[4px] bg-petrol-tint px-1.5 py-px font-mono text-[9px] font-semibold tracking-[0.05em] text-petrol dark:bg-white/10",
				className,
			)}
		>
			CODE EXECUTION
		</span>
	);
}

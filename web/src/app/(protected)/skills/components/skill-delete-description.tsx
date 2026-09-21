import { isDetached, isSourced, repoLabel, type SkillSummary } from "@/types/skills";

/**
 * The body of the "delete this skill?" confirmation, in one place because
 * what deleting *means* is not the same for the three kinds of skill and the
 * two screens that ask must not drift on it.
 *
 * The one worth saying out loud is the connected sourced skill. The
 * repository is the desired state and a sync converges on it, so deleting the
 * row here does not remove the skill — the next sync imports it again as
 * `new`, with a fresh id and no agent bindings. That is the right behaviour
 * for a one-way mirror, and it is astonishing if nobody says so before the
 * button. A detached skill has no repository to bring it back, so for it this
 * really is the end.
 */
export function SkillDeleteDescription({ skill }: { skill: SkillSummary | null }) {
	if (!skill) return null;
	// `??` would not do: `repoLabel` returns "" for a missing URL, not null.
	const repo = skill.sourceName || repoLabel(skill.sourceUrl) || "its repository";
	return (
		<>
			<span className="font-mono text-[12.5px] font-semibold text-petrol">{skill.name}</span>{" "}
			isn&apos;t enabled on any agent. Deleting it removes the SKILL.md and its files for
			everyone; threads that already used it are unaffected.
			{isSourced(skill) &&
				(isDetached(skill) ? (
					<> Nothing syncs it any more, so this is permanent.</>
				) : (
					<>
						{" "}
						<span className="font-semibold">
							It is still in {repo}, so the next sync brings it back
						</span>{" "}
						— as a new skill, enabled on nothing. To remove it for good, remove it from the
						repository first, or disconnect the repository.
					</>
				))}
		</>
	);
}

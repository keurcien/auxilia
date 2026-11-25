"use client";

import { UsedByList, agentUsedByItem } from "@/components/editor/used-by-list";
import type { BoundAgent } from "@/types/agents";

/**
 * The agents a skill is enabled on, as a right-panel block of the skill
 * page. Each row opens the agent — where the skill is disabled, and where
 * code execution is turned on if its scripts need it.
 */
export default function SkillUsedBy({ agents }: { agents: BoundAgent[] }) {
	return (
		<UsedByList
			className="mt-8"
			items={agents.map(agentUsedByItem)}
			emptyText="Not enabled on any agent yet. Add it from an agent's Skills section."
		/>
	);
}

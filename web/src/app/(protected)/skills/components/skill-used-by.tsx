"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import type { BoundAgent } from "@/types/agents";

/**
 * The agents a skill is enabled on, as a right-panel block of the skill
 * page. Each row opens the agent — where the skill is disabled, and where
 * code execution is turned on if its scripts need it.
 */
export default function SkillUsedBy({ agents }: { agents: BoundAgent[] }) {
	return (
		<div className="mt-8 flex flex-col">
			<div className="mb-3 flex min-h-[24px] shrink-0 items-center justify-between">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
					USED BY{" "}
					<span className="tracking-normal text-meta dark:text-panel-dim">{agents.length}</span>
				</span>
			</div>
			{agents.length === 0 ? (
				<div className="rounded-[10px] border border-dashed border-input px-4 py-6 text-center text-[13px] text-meta dark:text-panel-dim">
					Not enabled on any agent yet. Add it from an agent&apos;s Skills section.
				</div>
			) : (
				<div className="overflow-hidden rounded-[10px] border border-border bg-card">
					{agents.map((agent) => (
						<Link
							key={agent.id}
							href={`/agents/${agent.id}`}
							className="flex items-center gap-3 border-b border-hairline px-4 py-2.5 transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5"
						>
							<AgentAvatar color={agent.color} emoji={agent.emoji} size="xs" shape="tile" />
							<span className="min-w-0 flex-1 truncate font-mono text-[12.5px] font-semibold text-petrol">
								{agent.name}
							</span>
							<ChevronRight className="size-3.5 shrink-0 text-faint dark:text-panel-dim" />
						</Link>
					))}
				</div>
			)}
		</div>
	);
}

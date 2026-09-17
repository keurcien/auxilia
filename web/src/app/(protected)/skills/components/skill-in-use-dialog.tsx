"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import type { BoundAgent } from "@/types/agents";

interface SkillInUseDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	skillName: string | null;
	agents: BoundAgent[];
}

/**
 * The delete guard for a skill that agents still use. A delete never
 * propagates (design 23d): the dialog names every agent, links to each
 * one's editor, and offers nothing else — the fix is a setting there.
 */
export default function SkillInUseDialog({
	open,
	onOpenChange,
	skillName,
	agents,
}: SkillInUseDialogProps) {
	if (!skillName) return null;
	const count = agents.length;

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[480px]">
				<DialogHeader>
					<DialogTitle>Skill in use</DialogTitle>
					<DialogDescription>
						Can&apos;t delete{" "}
						<span className="font-mono text-[12.5px] font-semibold text-petrol">
							{skillName}
						</span>{" "}
						— it&apos;s enabled on {count === 1 ? "this agent" : `these ${count} agents`}.
						Disable it there first.
					</DialogDescription>
				</DialogHeader>

				<div className="max-h-[260px] overflow-y-auto rounded-[10px] border border-hairline dark:border-white/10 [scrollbar-width:thin]">
					{agents.map((agent) => (
						<Link
							key={agent.id}
							href={`/agents/${agent.id}`}
							className="flex items-center gap-2.5 border-b border-hairline px-3.5 py-2.5 transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5"
						>
							<AgentAvatar color={agent.color} emoji={agent.emoji} size="xs" shape="tile" />
							<span className="min-w-0 flex-1 truncate font-mono text-[12.5px] font-semibold text-petrol">
								{agent.name}
							</span>
							<ChevronRight className="size-3.5 shrink-0 text-faint dark:text-panel-dim" />
						</Link>
					))}
				</div>

				<DialogFooter>
					<DialogButton
						variant="outline"
						onClick={() => {
							onOpenChange(false);
						}}
					>
						Close
					</DialogButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

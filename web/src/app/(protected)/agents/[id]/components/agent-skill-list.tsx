"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, Sparkles, X } from "lucide-react";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { SearchBar } from "@/components/ui/search-bar";
import { useSkillsStore } from "@/stores/skills-store";
import type { AgentSkill } from "@/types/skills";

interface AgentSkillListProps {
	skillIds: string[];
	/** Display info for ids the store may not know yet (from agent.skills). */
	fallbackSkills?: AgentSkill[];
	readOnly?: boolean;
	onChange?: (skillIds: string[]) => void;
}

/**
 * The skills enabled on an agent — part of the config draft, saved with
 * the rest of the agent. A supervisor and its subagents share one skill set
 * at run time; the server refuses a save that would put two different
 * skills of one name in a graph.
 */
export default function AgentSkillList({
	skillIds,
	fallbackSkills = [],
	readOnly,
	onChange,
}: AgentSkillListProps) {
	const skills = useSkillsStore((state) => state.skills);
	const fetchSkills = useSkillsStore((state) => state.fetchSkills);
	const [dialogOpen, setDialogOpen] = useState(false);
	const [search, setSearch] = useState("");

	useEffect(() => {
		fetchSkills().catch(() => {});
	}, [fetchSkills]);

	const resolve = (id: string): AgentSkill =>
		skills.find((s) => s.id === id) ??
		fallbackSkills.find((s) => s.id === id) ?? {
			id,
			name: "unknown skill",
			description: "",
		};
	const enabled = skillIds.map(resolve);

	const candidates = useMemo(() => {
		const taken = new Set(skillIds);
		const term = search.trim().toLowerCase();
		return skills
			.filter((s) => !taken.has(s.id))
			.filter(
				(s) =>
					!term ||
					s.name.includes(term) ||
					s.description.toLowerCase().includes(term),
			)
			.sort((a, b) => a.name.localeCompare(b.name));
	}, [skills, skillIds, search]);

	return (
		<div className="mt-8 flex min-h-0 flex-col">
			<div className="mb-3 flex min-h-[24px] shrink-0 items-center justify-between">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
					SKILLS{" "}
					<span className="tracking-normal text-meta dark:text-panel-dim">
						{enabled.length}
					</span>
				</span>
				{!readOnly && (
					<button
						type="button"
						className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80"
						onClick={() => {
							setDialogOpen(true);
						}}
					>
						<Plus className="size-3" />
						Add skill
					</button>
				)}
			</div>

			{enabled.length > 0 ? (
				<div className="flex flex-col gap-2.5">
					{enabled.map((skill) => (
						<div
							key={skill.id}
							className="flex items-center gap-2.5 rounded-[10px] border border-border bg-card px-4 py-3"
						>
							<span className="flex size-[26px] shrink-0 items-center justify-center rounded-[6px] border border-border bg-card">
								<Sparkles className="size-3.5 text-petrol" />
							</span>
							<div className="min-w-0 flex-1">
								<Link
									href={`/skills/${skill.id}`}
									className="block truncate font-mono text-[13px] font-semibold text-foreground hover:text-petrol"
								>
									{skill.name}
								</Link>
								{skill.description && (
									<p className="truncate text-xs text-muted-foreground">
										{skill.description}
									</p>
								)}
							</div>
							{!readOnly && (
								<button
									type="button"
									aria-label={`Remove ${skill.name}`}
									className="cursor-pointer rounded p-1 text-meta transition-colors hover:text-destructive dark:text-panel-dim"
									onClick={() => {
										onChange?.(skillIds.filter((id) => id !== skill.id));
									}}
								>
									<X className="size-3.5" />
								</button>
							)}
						</div>
					))}
				</div>
			) : (
				<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
					No skills enabled
				</div>
			)}

			{!readOnly && (
				<Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
					<DialogContent className="sm:max-w-[560px] max-h-[600px]">
						<DialogHeader>
							<DialogTitle>Add skill</DialogTitle>
						</DialogHeader>
						<div className="flex flex-col gap-4 overflow-y-auto">
							<SearchBar
								placeholder="Search skills..."
								value={search}
								onChange={setSearch}
							/>
							{candidates.length > 0 ? (
								<div className="max-h-[400px] flex flex-col gap-2 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
									{candidates.map((candidate) => (
										<div
											key={candidate.id}
											className="flex items-center justify-between rounded-[10px] border border-hairline bg-canvas px-4 py-3 transition-colors hover:bg-sidebar dark:bg-white/5 dark:hover:bg-white/10"
										>
											<div className="min-w-0 flex-1">
												<p className="truncate font-mono text-[13px] font-semibold text-ink dark:text-panel-button">
													{candidate.name}
												</p>
												<p className="truncate text-[12px] text-label dark:text-panel-dim">
													{candidate.description}
												</p>
											</div>
											<button
												type="button"
												aria-label={`Add ${candidate.name}`}
												className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] border border-input text-label outline-none transition-colors hover:border-border-hover hover:text-ink dark:border-white/10 dark:hover:bg-white/10 dark:hover:text-panel-button"
												onClick={() => {
													onChange?.([...skillIds, candidate.id]);
													if (candidates.length <= 1) setDialogOpen(false);
												}}
											>
												<Plus className="size-3.5" />
											</button>
										</div>
									))}
								</div>
							) : (
								<div className="py-8 text-center text-sm text-muted-foreground">
									{skills.length === 0 ? (
										<>
											No skills in the workspace yet.{" "}
											<Link href="/skills/new" className="text-petrol underline">
												Create one
											</Link>
											.
										</>
									) : (
										"Every skill is already enabled."
									)}
								</div>
							)}
						</div>
					</DialogContent>
				</Dialog>
			)}
		</div>
	);
}

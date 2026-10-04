"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, X } from "lucide-react";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { SearchBar } from "@/components/ui/search-bar";
import { SkillAvatar } from "@/components/ui/skill-avatar";
import { SkillRequirementChip } from "@/app/(protected)/skills/components/skill-requirement-chip";
import { useSkillsStore } from "@/stores/skills-store";
import type { AgentSkill } from "@/types/skills";

interface AgentSkillListProps {
	skillIds: string[];
	/** Display info for ids the store may not know yet (from agent.skills). */
	fallbackSkills?: AgentSkill[];
	/** Whether the agent has a sandbox bound — what a skill's scripts need. */
	runsCode: boolean;
	readOnly?: boolean;
	onChange?: (skillIds: string[]) => void;
	/** Edit mode: open the tool picker on its sandbox choice. */
	onEnableCodeExecution?: () => void;
}

/**
 * The skills enabled on an agent — part of the config draft, saved with
 * the rest of the agent. A supervisor and its subagents share one skill set
 * at run time; the server refuses a save that would put two different
 * skills of one name in a graph.
 *
 * Attaching is always allowed (design 23c): a skill with scripts on an
 * agent without code execution stays attached and its instructions still
 * apply — the row says so, and in edit mode offers the fix in place.
 */
export default function AgentSkillList({
	skillIds,
	fallbackSkills = [],
	runsCode,
	readOnly,
	onChange,
	onEnableCodeExecution,
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
			emoji: null,
			color: null,
			imageRevision: null,
			scriptCount: 0,
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
				<span className="text-[10.5px] font-semibold text-label dark:text-muted-foreground">
					Skills{" "}
					<span className="tracking-normal text-meta dark:text-panel-dim">
						{enabled.length}
					</span>
				</span>
				{!readOnly && (
					<button
						type="button"
						className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
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
					{enabled.map((skill) => {
						const scriptsInactive = skill.scriptCount > 0 && !runsCode;
						return (
							<div
								key={skill.id}
								className="rounded-[10px] border border-border bg-card px-4 py-3"
							>
								<div className="flex items-center gap-3">
									<SkillAvatar
										skillId={skill.id}
										name={skill.name}
										emoji={skill.emoji}
										color={skill.color}
										imageRevision={skill.imageRevision}
										size="xs"
									/>
									<div className="min-w-0 flex-1">
										<div className="flex min-w-0 items-center gap-2">
											<Link
												href={`/skills/${skill.id}`}
												className="truncate text-[12.5px] font-semibold text-petrol hover:underline dark:text-panel-terminal"
											>
												{skill.name}
											</Link>
											{skill.scriptCount > 0 && (
												<SkillRequirementChip scriptCount={skill.scriptCount} />
											)}
										</div>
										{skill.description && (
											<p className="mt-0.5 truncate text-xs text-muted-foreground">
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
								{scriptsInactive &&
									(readOnly ? (
										<p className="mt-2 pl-[38px] text-[11px] leading-[1.5] text-meta dark:text-panel-dim">
											scripts inactive, this agent doesn&apos;t run code. Instructions
											still apply.
										</p>
									) : (
										<div className="mt-2.5 ml-[38px] flex items-center gap-2.5 rounded-[7px] border border-[#F0DCC2] bg-[#FDF9F0] px-3 py-2 dark:border-[#7A5C1E]/40 dark:bg-[#7A5C1E]/10">
											<span className="min-w-0 flex-1 text-[11.5px] leading-[1.45] text-[#7A5C1E] dark:text-[#E8C27A]">
												Attached, but its {skill.scriptCount} script
												{skill.scriptCount === 1 ? "" : "s"} won&apos;t run here, this
												agent doesn&apos;t run code. Instructions still apply.
											</span>
											{onEnableCodeExecution && (
												<button
													type="button"
													className="shrink-0 cursor-pointer rounded-[6px] border border-[#E2C89A] bg-card px-2.5 py-[5px] text-[11.5px] font-semibold text-[#7A5C1E] transition-colors hover:bg-[#FBF3E2] dark:border-[#7A5C1E]/50 dark:text-[#E8C27A] dark:hover:bg-[#7A5C1E]/20"
													onClick={onEnableCodeExecution}
												>
													Turn on code execution
												</button>
											)}
										</div>
									))}
							</div>
						);
					})}
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
							<DialogDescription>
								Any skill in the workspace. Instructions apply to every agent;
								scripts only run on agents with code execution.
							</DialogDescription>
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
											className="flex items-center gap-3 rounded-[10px] border border-hairline bg-canvas px-4 py-3 transition-colors hover:bg-sidebar dark:bg-white/5 dark:hover:bg-white/10"
										>
											<div className="min-w-0 flex-1">
												<div className="flex min-w-0 items-center gap-2">
													<p className="truncate text-[13px] font-semibold text-ink dark:text-panel-button">
														{candidate.name}
													</p>
													<SkillRequirementChip scriptCount={candidate.scriptCount} />
												</div>
												<p className="mt-0.5 truncate text-[12px] text-label dark:text-panel-dim">
													{candidate.description}
												</p>
												{candidate.scriptCount > 0 && !runsCode && (
													<p className="mt-0.5 text-[10.5px] text-[#B07A2A]">
														scripts won&apos;t run here, this agent doesn&apos;t run
														code
													</p>
												)}
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
											<Link href="/skills/new" className="text-petrol underline dark:text-panel-terminal">
												Write one
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

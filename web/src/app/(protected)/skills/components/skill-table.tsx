"use client";

import { useRouter } from "next/navigation";
import { GitCompareArrows, Pencil, PencilLine, Trash2, Unplug } from "lucide-react";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import type { BoundAgent } from "@/types/agents";
import { isDetached, isSourced, repoLabel, shortRevision, type SkillSummary } from "@/types/skills";
import { relativeTime } from "../lib/relative-time";
import { SkillRequirementChip } from "./skill-requirement-chip";
import { SourceHostTile } from "./source-host-tile";

interface SkillTableProps {
	skills: SkillSummary[];
	isLoading: boolean;
	search: string;
	onClearSearch: () => void;
	onDelete: (skill: SkillSummary) => void;
}

/**
 * The library as a table (design 23a/13b): mono teal name + description,
 * the requirement chip, how many agents use it, when it last changed, and a
 * row menu. Rows open the skill.
 */
/**
 * The agents a skill is enabled on, as overlapping avatars — a supervisor
 * and the subagents sharing its skill set look like the group they are,
 * which a bare "3 agents" never showed. Past four the rest become a count,
 * and every avatar carries its agent's name for anyone hovering.
 */
function UsedByAvatars({ agents }: { agents: BoundAgent[] }) {
	if (agents.length === 0) {
		return <span className="font-mono text-[11px] text-ghost dark:text-panel-dim">—</span>;
	}
	const shown = agents.slice(0, 4);
	const rest = agents.length - shown.length;
	return (
		<span className="flex items-center" title={agents.map((a) => a.name).join(", ")}>
			{shown.map((agent) => (
				<span
					key={agent.id}
					className="-ml-1.5 rounded-[5px] ring-2 ring-card first:ml-0 dark:ring-[#12191C]"
				>
					<AgentAvatar color={agent.color} emoji={agent.emoji} size="xs" shape="tile" />
				</span>
			))}
			{rest > 0 && (
				<span className="ml-1.5 font-mono text-[11px] text-meta dark:text-panel-dim">
					+{rest}
				</span>
			)}
		</span>
	);
}

/**
 * Where a skill comes from — and so where it is edited. Three kinds, said in
 * the same place rather than left to be inferred from a missing line: a
 * skill written in the app, one pinned to a connected repository (with its
 * host's mark and the commit it is pinned to), and one whose repository has
 * been disconnected — still pinned, still running, its content edited
 * nowhere until it is connected again.
 */
function SourceCell({ skill }: { skill: SkillSummary }) {
	if (!isSourced(skill)) {
		return (
			<span className="flex min-w-0 items-center gap-1.5" title="Written in auxilia — edit it here">
				<PencilLine className="size-3.5 shrink-0 text-meta dark:text-panel-dim" />
				<span className="truncate font-mono text-[11px] text-meta dark:text-panel-dim">in-app</span>
			</span>
		);
	}
	if (isDetached(skill)) {
		// The repository is named even though it is gone: `sourceUrl` outlives
		// the link precisely so "connect it again" is an instruction and not a
		// riddle. Without it the row said only "disconnected", and the one
		// action it suggested needed a URL nothing on the page still held.
		const repo = repoLabel(skill.sourceUrl);
		return (
			<span
				className="flex min-w-0 items-center gap-1.5"
				title={`From ${skill.sourceUrl ?? "a repository"}, which is no longer connected${
					skill.sourcePath ? ` · ${skill.sourcePath}` : ""
				}${
					skill.sourceRevision ? ` at ${shortRevision(skill.sourceRevision)}` : ""
				} — connect it again to change this skill`}
			>
				<Unplug className="size-3.5 shrink-0 text-meta dark:text-panel-dim" />
				<span className="min-w-0">
					<span className="block truncate font-mono text-[11px] text-meta dark:text-panel-dim">
						{repo || "disconnected"}
					</span>
					<span className="block truncate font-mono text-[10px] text-meta dark:text-panel-dim">
						{repo ? "disconnected" : shortRevision(skill.sourceRevision)}
					</span>
				</span>
			</span>
		);
	}
	return (
		<span
			className="flex min-w-0 items-center gap-2"
			title={`Synced from ${skill.sourceName ?? "a repository"}${
				skill.sourcePath ? ` · ${skill.sourcePath}` : ""
			}${skill.sourceRevision ? ` at ${shortRevision(skill.sourceRevision)}` : ""} — edited there, not here`}
		>
			<SourceHostTile kind={skill.sourceKind ?? "github"} size={20} />
			<span className="min-w-0">
				<span className="block truncate font-mono text-[11px] text-foreground">
					{skill.sourceName ?? "repository"}
				</span>
				{skill.sourceRevision && (
					<span className="block truncate font-mono text-[10px] text-meta dark:text-panel-dim">
						{shortRevision(skill.sourceRevision)}
					</span>
				)}
			</span>
		</span>
	);
}

export default function SkillTable({
	skills,
	isLoading,
	search,
	onClearSearch,
	onDelete,
}: SkillTableProps) {
	const router = useRouter();

	const columns: DataTableColumn<SkillSummary>[] = [
		{
			key: "name",
			header: "Skill",
			width: "minmax(0, 1.5fr)",
			cell: (skill) => (
				<div className="min-w-0">
					<div className="flex min-w-0 items-center gap-2">
						<span className="truncate font-mono text-[12.5px] font-semibold text-petrol">
							{skill.name}
						</span>
						{skill.updateAvailable && (
							<span className="shrink-0 rounded-[4px] bg-warning-bg px-1.5 py-px font-mono text-[9px] font-semibold tracking-[0.05em] text-warning">
								UPDATE
							</span>
						)}
						{skill.missingUpstream && (
							<span
								title="The last sync no longer found this skill in its repository. It keeps working as pinned."
								className="shrink-0 rounded-[4px] bg-neutral-bg px-1.5 py-px font-mono text-[9px] font-semibold tracking-[0.05em] text-subtle dark:bg-white/10"
							>
								GONE UPSTREAM
							</span>
						)}
					</div>
					<div className="mt-px truncate text-[12px] text-subtle dark:text-muted-foreground">
						{skill.description}
					</div>
				</div>
			),
		},
		{
			key: "source",
			header: "Source",
			width: "200px",
			mobileWidth: "auto",
			cell: (skill) => <SourceCell skill={skill} />,
		},
		{
			key: "requires",
			header: "Requires",
			width: "128px",
			hideBelowMd: true,
			// The constraint, not a boolean. Almost every skill runs anywhere, so
			// a `false` column would be a column of "no" with the answer hidden
			// among it; marking only the exceptions means the eye lands on the
			// rows that actually restrict which agent can use them. Same rule the
			// chip follows everywhere else it appears.
			cell: (skill) =>
				skill.scriptCount > 0 ? (
					<SkillRequirementChip scriptCount={skill.scriptCount} />
				) : (
					<span
						title="Instructions only — this skill runs on any agent."
						className="font-mono text-[11px] text-ghost dark:text-panel-dim"
					>
						—
					</span>
				),
		},
		{
			key: "used",
			header: "Used by",
			width: "110px",
			hideBelowMd: true,
			cell: (skill) => <UsedByAvatars agents={skill.agents} />,
		},
		{
			key: "updated",
			header: "Updated",
			width: "100px",
			hideBelowMd: true,
			cell: (skill) => (
				<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
					{relativeTime(skill.updatedAt)}
				</span>
			),
		},
		{
			key: "actions",
			header: "",
			width: "44px",
			mobileWidth: "auto",
			cell: (skill) => (
				<div
					className="flex justify-end"
					onClick={(e) => {
						e.stopPropagation();
					}}
				>
					<DropdownMenu
						items={[
							{
								label: skill.canEdit ? "Edit" : "Open",
								icon: <Pencil />,
								onClick: () => {
									router.push(`/skills/${skill.id}${skill.canEdit ? "?edit=1" : ""}`);
								},
							},
							...(skill.updateAvailable
								? [
										{
											label: "Review update",
											icon: <GitCompareArrows />,
											onClick: () => {
												router.push(`/skills/${skill.id}?review=1`);
											},
										},
									]
								: []),
							...(skill.canManage
								? [
										{ separator: true as const },
										{
											label: "Delete skill",
											icon: <Trash2 />,
											destructive: true,
											onClick: () => {
												onDelete(skill);
											},
										},
									]
								: []),
						]}
					/>
				</div>
			),
		},
	];

	return (
		<DataTable
			columns={columns}
			rows={skills}
			rowKey={(skill) => skill.id}
			isLoading={isLoading}
			scrollBody
			onRowClick={(skill) => {
				router.push(`/skills/${skill.id}`);
			}}
			emptyMessage={
				search ? (
					<span>
						No skill matches “{search}”.{" "}
						<button
							type="button"
							onClick={onClearSearch}
							className="cursor-pointer font-semibold text-petrol hover:underline"
						>
							Clear search
						</button>
					</span>
				) : (
					"No skills yet."
				)
			}
		/>
	);
}

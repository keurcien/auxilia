"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Copy, GitCompareArrows, Pencil, PencilLine, Trash2, Unplug } from "lucide-react";
import { toast } from "sonner";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import {
	BulkConfirmDialog,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { BulkActionBar } from "@/components/ui/bulk-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { GroupedCardTree } from "@/components/ui/grouped-card-tree";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import { SkillAvatar } from "@/components/ui/skill-avatar";
import type { ViewMode } from "@/components/ui/view-toggle";
import { useRowSelection } from "@/hooks/use-row-selection";
import { getApiErrorMessage, toApiError } from "@/lib/api/errors";
import { buildGroupTree, flattenGroupTree } from "@/lib/groups";
import { useAppearanceStore } from "@/stores/appearance-store";
import { useSkillsStore } from "@/stores/skills-store";
import type { BoundAgent } from "@/types/agents";
import {
	isDetached,
	isSourced,
	repoLabel,
	shortRevision,
	SKILL_NAME_MAX,
	type SkillSummary,
} from "@/types/skills";
import { relativeTime } from "../lib/relative-time";
import { SkillRequirementChip } from "./skill-requirement-chip";
import { SourceHostTile } from "./source-host-tile";
import {
	composeSkillMarkdown,
	splitSkillMarkdown,
	yamlScalar,
} from "../lib/skill-form";

interface SkillTableProps {
	mode: ViewMode;
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
		return <span className="text-[11px] text-ghost dark:text-panel-dim">None</span>;
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
					<AgentAvatar
						agentId={agent.id}
						name={agent.name}
						imageRevision={agent.imageRevision}
						color={agent.color}
						emoji={agent.emoji}
						size="xs"
					/>
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
	const appName = useAppearanceStore((state) => state.appearance.appName);
	if (!isSourced(skill)) {
		return (
			<span className="flex min-w-0 items-center gap-1.5" title={`Written in ${appName}, edit it here`}>
				<PencilLine className="size-3.5 shrink-0 text-meta dark:text-panel-dim" />
				<span className="truncate text-[11px] text-meta dark:text-panel-dim">in-app</span>
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
					skill.sourcePath ? `, ${skill.sourcePath}` : ""
				}${
					skill.sourceRevision ? ` at ${shortRevision(skill.sourceRevision)}` : ""
				}, connect it again to change this skill`}
			>
				<Unplug className="size-3.5 shrink-0 text-meta dark:text-panel-dim" />
				<span className="min-w-0">
					<span className="block truncate text-[11px] text-meta dark:text-panel-dim">
						{repo || "disconnected"}
					</span>
					<span className="block truncate text-[10px] text-meta dark:text-panel-dim">
						{repo ? (
							"disconnected"
						) : (
							<span className="font-mono">{shortRevision(skill.sourceRevision)}</span>
						)}
					</span>
				</span>
			</span>
		);
	}
	return (
		<span
			className="flex min-w-0 items-center gap-2"
			title={`Synced from ${skill.sourceName ?? "a repository"}${
				skill.sourcePath ? `, ${skill.sourcePath}` : ""
			}${skill.sourceRevision ? ` at ${shortRevision(skill.sourceRevision)}` : ""}, edited there, not here`}
		>
			<SourceHostTile kind={skill.sourceKind ?? "github"} size={20} />
			<span className="min-w-0">
				<span className="block truncate text-[11px] text-foreground">
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
	mode,
	skills,
	isLoading,
	search,
	onClearSearch,
	onDelete,
}: SkillTableProps) {
	const router = useRouter();
	const groupTree = buildGroupTree(skills);
	const deleteSkill = useSkillsStore((state) => state.deleteSkill);
	const getSkill = useSkillsStore((state) => state.getSkill);
	const createSkill = useSkillsStore((state) => state.createSkill);
	const workspaceSkills = useSkillsStore((state) => state.skills);
	const [bulkOpen, setBulkOpen] = useState(false);
	const orderedSkills = flattenGroupTree(groupTree);
	const selection = useRowSelection({
		orderedIds: orderedSkills.map((skill) => skill.id),
		eligibleIds: orderedSkills
			.filter((skill) => skill.canManage)
			.map((skill) => skill.id),
	});
	const selectedSkills = orderedSkills.filter((skill) =>
		selection.selectedIds.has(skill.id),
	);
	const bulkItems = selectedSkills.map((skill) => ({
		id: skill.id,
		name: skill.name,
		blockedReason:
			skill.agentCount > 0
				? `Used by ${skill.agentCount} agent${skill.agentCount === 1 ? "" : "s"}.`
				: undefined,
	}));

	const duplicateSkill = async (skill: SkillSummary) => {
		try {
			const full = await getSkill(skill.id);
			if (full.files.length > 0) {
				toast.error(
					"Skills with repository files cannot be duplicated as standalone skills.",
				);
				return;
			}
			const names = new Set(workspaceSkills.map((candidate) => candidate.name));
			for (let copyNumber = 1; copyNumber <= 999; copyNumber += 1) {
				const suffix =
					copyNumber === 1 ? "-copy" : `-copy-${copyNumber}`;
				const copyName = `${skill.name.slice(
					0,
					SKILL_NAME_MAX - suffix.length,
				)}${suffix}`;
				if (names.has(copyName)) continue;
				const fields = splitSkillMarkdown(full.content);
				const content = fields
					? composeSkillMarkdown({ ...fields, name: copyName })
					: full.content.replace(
							/^name:[ \t]*.*$/m,
							`name: ${yamlScalar(copyName)}`,
						);
				try {
					const created = await createSkill({
						content,
						files: [],
						group: full.group,
						emoji: full.emoji,
						color: full.color,
						visibility: full.visibility,
						teamIds: full.teamIds,
					});
					toast.success(`Duplicated as “${created.name}”.`);
					router.push(`/skills/${created.id}?edit=1`);
					return;
				} catch (error: unknown) {
					if (toApiError(error).status !== 409) throw error;
					names.add(copyName);
				}
			}
			throw new Error("Could not find an available skill name.");
		} catch (error: unknown) {
			toast.error(getApiErrorMessage(error, "Could not duplicate the skill."));
		}
	};

	const masterCheckbox = !selection.selectionMode ? (
		<Checkbox
			checked={
				selection.allSelected
					? true
					: selection.someSelected
						? "indeterminate"
						: false
			}
			aria-label={selection.allSelected ? "Unselect all skills" : "Select all skills"}
			onCheckedChange={selection.toggleAll}
		/>
	) : null;

	const columns: DataTableColumn<SkillSummary>[] = [
		{
			key: "name",
			header: selection.selectionMode ? (
				""
			) : (
				<span className="flex items-center gap-2.5">
					{masterCheckbox}
					<button
						type="button"
						onClick={selection.toggleAll}
						className="cursor-pointer text-[12px]! font-semibold text-foreground hover:text-petrol"
					>
						Select all
					</button>
				</span>
			),
			width: "minmax(220px, 1.5fr)",
			cell: (skill) => (
				<div className="flex min-w-0 items-center gap-2.5">
					<SelectableLeading
						selected={selection.isSelected(skill.id)}
						selectionMode={selection.selectionMode}
						disabled={!skill.canManage}
						label={`Select ${skill.name}`}
						onToggle={(shiftKey) => {
							selection.toggle(skill.id, shiftKey);
						}}
						className="size-6"
					>
						<SkillAvatar
							skillId={skill.id}
							name={skill.name}
							emoji={skill.emoji}
							color={skill.color}
							imageRevision={skill.imageRevision}
							size="xs"
						/>
					</SelectableLeading>
					<div className="min-w-0">
						<div className="flex min-w-0 items-center gap-2">
							<span className="truncate text-[12.5px] font-semibold text-petrol dark:text-panel-terminal">
								{skill.name}
							</span>
							{skill.updateAvailable && (
								<span className="shrink-0 rounded-[4px] bg-warning-bg px-1.5 py-px text-[9px] font-semibold text-warning">
									Update
								</span>
							)}
							{skill.missingUpstream && (
								<span
									title="The last sync no longer found this skill in its repository. It keeps working as pinned."
									className="shrink-0 rounded-[4px] bg-neutral-bg px-1.5 py-px text-[9px] font-semibold text-subtle dark:bg-white/10"
								>
									Gone upstream
								</span>
							)}
						</div>
						<div className="mt-px truncate text-[12px] text-subtle dark:text-muted-foreground">
							{skill.description}
						</div>
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
			key: "visibility",
			header: "Visibility",
			width: "120px",
			cell: (skill) => <VisibilityBadge visibility={skill.visibility} />,
		},
		{
			key: "requires",
			header: "Requires",
			width: "128px",
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
						title="Instructions only, this skill runs on any agent."
						className="text-[11px] text-ghost dark:text-panel-dim"
					>
						None
					</span>
				),
		},
		{
			key: "used",
			header: "Used by",
			width: "110px",
			cell: (skill) => <UsedByAvatars agents={skill.agents} />,
		},
		{
			key: "updated",
			header: "Updated",
			width: "100px",
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
								label: skill.canEdit || skill.canManage ? "Edit" : "Open",
								icon: <Pencil />,
								onClick: () => {
									router.push(
										`/skills/${skill.id}${
											skill.canEdit || skill.canManage ? "?edit=1" : ""
										}`,
									);
								},
							},
							...(skill.fileCount === 0 && (skill.canEdit || skill.canManage)
								? [
										{
											label: "Duplicate",
											icon: <Copy />,
											onClick: () => {
												void duplicateSkill(skill);
											},
										},
									]
								: []),
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

	if (mode === "cards") {
		if (isLoading) return null;
		if (skills.length === 0) {
			return (
				<div className="flex min-h-48 items-center justify-center rounded-[10px] border border-dashed border-border px-6 text-center text-[13px] text-subtle">
					{search ? (
						<span>
							No skill matches “{search}”.{" "}
							<button
								type="button"
								onClick={onClearSearch}
								className="cursor-pointer font-semibold text-petrol hover:underline dark:text-panel-terminal"
							>
								Clear search
							</button>
						</span>
					) : (
						"No skills yet."
					)}
				</div>
			);
		}

		return (
			<>
				<BulkActionBar
					selectedCount={selection.selectedCount}
					totalCount={orderedSkills.filter((skill) => skill.canManage).length}
					allSelected={selection.allSelected}
					someSelected={selection.someSelected}
					onToggleAll={selection.toggleAll}
					onClear={selection.clear}
					actionLabel="Delete"
					onAction={() => {
						setBulkOpen(true);
					}}
					showWhenEmpty
				/>
				<GroupedCardTree
				tree={groupTree}
				storageKey="skills:card-group"
				renderItem={(skill, index) => (
					<article
						key={skill.id}
						className={`group relative flex min-h-[200px] animate-in flex-col rounded-xl border bg-white p-4 fade-in slide-in-from-bottom-3 transition-[border-color,box-shadow] duration-400 ease-out hover:shadow-[0_3px_10px_rgba(30,45,40,0.06)] dark:bg-card ${
							selection.isSelected(skill.id)
								? "border-petrol/45 shadow-[inset_0_0_0_1px_rgba(38,103,81,0.12)] dark:border-petrol/60"
								: "border-[#e1ebe6] hover:border-[#cfe0d8] dark:border-white/10 dark:hover:border-white/20"
						}`}
						style={{
							animationDelay: `${index * 40}ms`,
							animationFillMode: "both",
						}}
					>
						<Link
							href={`/skills/${skill.id}`}
							onClick={(event) => {
								if (!selection.selectionMode || !skill.canManage) return;
								event.preventDefault();
								selection.toggle(skill.id, event.shiftKey);
							}}
							className="absolute inset-0 rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-petrol"
						>
							<span className="sr-only">Open {skill.name}</span>
						</Link>
						<div className="pointer-events-none flex min-w-0 flex-wrap items-start justify-between gap-2">
							<div className="flex min-w-[120px] flex-1 items-start gap-2.5">
								<SelectableLeading
									selected={selection.isSelected(skill.id)}
									selectionMode={selection.selectionMode}
									disabled={!skill.canManage}
									label={`Select ${skill.name}`}
									onToggle={(shiftKey) => {
										selection.toggle(skill.id, shiftKey);
									}}
									className="pointer-events-auto z-10 size-8"
								>
									<SkillAvatar
										skillId={skill.id}
										name={skill.name}
										emoji={skill.emoji}
										color={skill.color}
										imageRevision={skill.imageRevision}
										size="sm"
									/>
								</SelectableLeading>
								<div className="min-w-0">
									<h2 className="truncate font-mono text-[13.5px] font-semibold text-petrol dark:text-panel-terminal">
										{skill.name}
									</h2>
									<div className="mt-2">
										<SourceCell skill={skill} />
									</div>
								</div>
							</div>
							<div className="ml-auto flex max-w-full shrink-0 flex-wrap justify-end gap-1">
								{skill.updateAvailable && (
									<span className="rounded-[4px] bg-warning-bg px-1.5 py-px text-[9px] font-semibold text-warning">
										Update
									</span>
								)}
								{skill.missingUpstream && (
									<span className="rounded-[4px] bg-neutral-bg px-1.5 py-px text-[9px] font-semibold text-subtle dark:bg-white/10">
										Gone upstream
									</span>
								)}
							</div>
						</div>
						<p className="pointer-events-none mt-3 line-clamp-3 min-h-[57px] flex-1 text-[12.5px] leading-[1.5] text-subtle dark:text-muted-foreground">
							{skill.description}
						</p>
						<div className="pointer-events-none mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[#edf2ef] pt-3 dark:border-white/5">
							<div>
								{skill.scriptCount > 0 ? (
									<SkillRequirementChip scriptCount={skill.scriptCount} />
								) : (
									<span className="text-[11px] text-ghost dark:text-panel-dim">
										Instructions only
									</span>
								)}
							</div>
							<UsedByAvatars agents={skill.agents} />
						</div>
						<div className="relative z-10 mt-3 flex items-center justify-between">
							<span className="pointer-events-none font-mono text-[10.5px] text-meta dark:text-panel-dim">
								Updated {relativeTime(skill.updatedAt)}
							</span>
							<DropdownMenu
								items={[
									{
										label:
											skill.canEdit || skill.canManage ? "Edit" : "Open",
										icon: <Pencil />,
										onClick: () => {
											router.push(
												`/skills/${skill.id}${
													skill.canEdit || skill.canManage ? "?edit=1" : ""
												}`,
											);
										},
									},
									...(skill.fileCount === 0 &&
									(skill.canEdit || skill.canManage)
										? [
												{
													label: "Duplicate",
													icon: <Copy />,
													onClick: () => {
														void duplicateSkill(skill);
													},
												},
											]
										: []),
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
					</article>
				)}
				/>
				<BulkConfirmDialog
					open={bulkOpen}
					onOpenChange={setBulkOpen}
					title="Delete selected skills?"
					description="Available skills will be removed permanently. Skills currently used by agents stay untouched."
					items={bulkItems}
					confirmLabel="Delete"
					busyLabel="Deleting…"
					onConfirm={async (items) => {
						const results = await Promise.allSettled(
							items.map((item) => deleteSkill(item.id)),
						);
						const succeeded: string[] = [];
						const failures: BulkFailure[] = [];
						results.forEach((result, index) => {
							const item = items.at(index);
							if (!item) return;
							if (result.status === "fulfilled") succeeded.push(item.id);
							else
								failures.push({
									id: item.id,
									name: item.name,
									message: getApiErrorMessage(result.reason, "Delete failed."),
								});
						});
						selection.remove(succeeded);
						return failures;
					}}
				/>
			</>
		);
	}

	return (
		<>
			<BulkActionBar
				selectedCount={selection.selectedCount}
				totalCount={orderedSkills.filter((skill) => skill.canManage).length}
				allSelected={selection.allSelected}
				someSelected={selection.someSelected}
				onToggleAll={selection.toggleAll}
				onClear={selection.clear}
				actionLabel="Delete"
				onAction={() => {
					setBulkOpen(true);
				}}
			/>
			<DataTable
				columns={columns}
				rows={skills}
				rowKey={(skill) => skill.id}
				isLoading={isLoading}
				isRowSelected={(skill) => selection.isSelected(skill.id)}
				selectionMode={selection.selectionMode}
				isRowSelectable={(skill) => skill.canManage}
				onRowSelectionClick={(skill, shiftKey) => {
					selection.toggle(skill.id, shiftKey);
				}}
				scrollBody
				minTableWidth="1060px"
				bleedOnNarrow
				groupTree={{
					...groupTree,
					storageKey: "skills:table-group",
				}}
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
								className="cursor-pointer font-semibold text-petrol hover:underline dark:text-panel-terminal"
							>
								Clear search
							</button>
						</span>
					) : (
						"No skills yet."
					)
				}
			/>
			<BulkConfirmDialog
				open={bulkOpen}
				onOpenChange={setBulkOpen}
				title="Delete selected skills?"
				description="Available skills will be removed permanently. Skills currently used by agents stay untouched."
				items={bulkItems}
				confirmLabel="Delete"
				busyLabel="Deleting…"
				onConfirm={async (items) => {
					const results = await Promise.allSettled(
						items.map((item) => deleteSkill(item.id)),
					);
					const succeeded: string[] = [];
					const failures: BulkFailure[] = [];
					results.forEach((result, index) => {
						const item = items.at(index);
						if (!item) return;
						if (result.status === "fulfilled") succeeded.push(item.id);
						else
							failures.push({
								id: item.id,
								name: item.name,
								message: getApiErrorMessage(result.reason, "Delete failed."),
							});
					});
					selection.remove(succeeded);
					return failures;
				}}
			/>
		</>
	);
}

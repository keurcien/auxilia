"use client";

import { useRouter } from "next/navigation";
import { Download, GitCompareArrows, Pencil, Trash2 } from "lucide-react";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { API_BASE_URL } from "@/lib/api/client";
import { shortRevision, type SkillSummary } from "@/types/skills";
import { relativeTime } from "../lib/relative-time";
import { SkillRequirementChip } from "./skill-requirement-chip";

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
					{skill.sourceName && (
						<div className="mt-0.5 truncate font-mono text-[10.5px] text-meta dark:text-panel-dim">
							from {skill.sourceName}
							{skill.sourceRevision ? ` @ ${shortRevision(skill.sourceRevision)}` : ""}
						</div>
					)}
				</div>
			),
		},
		{
			key: "requires",
			header: "Requires",
			width: "230px",
			mobileWidth: "auto",
			cell: (skill) => <SkillRequirementChip scriptCount={skill.scriptCount} />,
		},
		{
			key: "used",
			header: "Used by",
			width: "110px",
			hideBelowMd: true,
			cell: (skill) =>
				skill.agentCount > 0 ? (
					<span className="font-mono text-[11px] text-subtle dark:text-muted-foreground">
						{skill.agentCount} agent{skill.agentCount === 1 ? "" : "s"}
					</span>
				) : (
					<span className="font-mono text-[11px] text-ghost dark:text-panel-dim">—</span>
				),
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
							{
								label: "Export as zip",
								icon: <Download />,
								onClick: () => {
									window.location.assign(`${API_BASE_URL}/skills/${skill.id}/export`);
								},
							},
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

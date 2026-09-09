"use client";

import { useRouter } from "next/navigation";
import { Download, FileText, MoreVertical, Pencil, Trash2 } from "lucide-react";
import { SkillSummary } from "@/types/skills";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { API_BASE_URL } from "@/lib/api/client";

interface SkillCardProps {
	skill: SkillSummary;
	onDelete: (skill: SkillSummary) => void;
}

function relativeTime(dateStr: string): string {
	const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
	if (seconds < 60) return "just now";
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;
	return new Date(dateStr).toLocaleDateString();
}

export default function SkillCard({ skill, onDelete }: SkillCardProps) {
	const router = useRouter();
	const open = () => {
		router.push(`/skills/${skill.id}`);
	};

	return (
		<div
			className="group flex h-full flex-col gap-3 rounded-2xl border border-[#E9EEEB] dark:border-white/10 bg-white dark:bg-card p-5 cursor-pointer transition-[border-color,box-shadow] duration-[130ms] ease-out hover:border-[#D7E0DB] dark:hover:border-white/20 hover:shadow-[0_6px_18px_-4px_rgba(33,36,31,0.08)]"
			onClick={open}
		>
			<div className="flex min-h-[30px] min-w-0 items-center gap-2.5">
				<div className="min-w-0 flex-1 truncate font-mono text-[15px] font-semibold tracking-[-0.01em] text-petrol">
					{skill.name}
				</div>
				<div
					onClick={(e) => {
						e.stopPropagation();
					}}
				>
					<DropdownMenu
						trigger={
							<button
								type="button"
								className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta opacity-0 transition-all hover:bg-hover hover:text-ink group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:bg-hover data-[state=open]:opacity-100 dark:hover:bg-white/10 dark:hover:text-panel-button"
							>
								<MoreVertical className="size-[15px]" />
								<span className="sr-only">Skill options</span>
							</button>
						}
						items={[
							{
								label: skill.canEdit ? "Edit" : "Open",
								icon: <Pencil />,
								onClick: open,
							},
							{
								label: "Export",
								icon: <Download />,
								onClick: () => {
									window.location.assign(
										`${API_BASE_URL}/skills/${skill.id}/export`,
									);
								},
							},
							...(skill.canEdit
								? [
										{ separator: true as const },
										{
											label: "Delete",
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
			</div>

			<p className="flex-1 font-[family-name:var(--font-dm-sans)] text-[13.5px] leading-[1.45] text-[#6B7F76] dark:text-muted-foreground line-clamp-2">
				{skill.description}
			</p>

			<div className="flex flex-wrap items-center gap-2 border-t border-[#F0F3F1] dark:border-white/5 pt-3.5 font-[family-name:var(--font-dm-sans)] text-[12.5px] text-[#6B7F76] dark:text-muted-foreground">
				<span className="flex h-[30px] items-center gap-1.5 rounded-full border border-[#ECF1EE] dark:border-white/10 bg-[#F4F7F5] dark:bg-white/5 px-3 font-medium text-[#4A5B53] dark:text-white/80">
					<FileText className="size-[13px] shrink-0 text-[#7C8C84] dark:text-muted-foreground" />
					{skill.fileCount === 0
						? "SKILL.md only"
						: `${skill.fileCount} file${skill.fileCount === 1 ? "" : "s"}`}
				</span>
				<span className="ml-auto">Updated {relativeTime(skill.updatedAt)}</span>
			</div>
		</div>
	);
}

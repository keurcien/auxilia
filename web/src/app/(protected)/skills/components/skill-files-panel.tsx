"use client";

import { useState } from "react";
import Link from "next/link";
import { isScriptPath, shortRevision, type Skill, type SkillFile } from "@/types/skills";
import { CodeBlock } from "@/components/ai-elements/code-block";
import { PETROL_MONO_THEME } from "@/lib/shiki-petrol-mono";
import { cn } from "@/lib/utils";
import { formatBytes, skillFileSize } from "../lib/skill-form";
import { FileTypeIcon, skillFileLanguage } from "./file-type-icon";

interface SkillFilesPanelProps {
	files: SkillFile[];
	/** Undefined while creating; carries the provenance line when sourced. */
	skill?: Skill;
}

/**
 * The supporting files of a skill: one tab per file, the selected one shown
 * with syntax highlighting for its extension.
 *
 * Read-only, always. Files reach the library only through a repository, so
 * this panel renders a sourced skill's pinned content and nothing here can
 * change it — the repository is the editor. Anything under `scripts/` is
 * what makes a skill need an agent with code execution, so the panel counts
 * those separately.
 */
export default function SkillFilesPanel({ files, skill }: SkillFilesPanelProps) {
	const [selected, setSelected] = useState(0);
	const current = files[Math.min(selected, files.length - 1)];

	if (files.length === 0) {
		return (
			<div className="flex min-h-0 flex-1 flex-col">
				<Heading count={0} skill={skill} />
				<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
					No supporting files — this skill runs on any agent.
				</div>
			</div>
		);
	}

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<Heading count={files.length} skill={skill} />
			<div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-[10px] border border-border bg-card">
				<div className="flex shrink-0 overflow-x-auto border-b border-border [scrollbar-width:thin]">
					{files.map((file, index) => (
						<button
							key={`${index}-${file.path}`}
							type="button"
							onClick={() => {
								setSelected(index);
							}}
							className={cn(
								"flex shrink-0 cursor-pointer items-center gap-1.5 border-r border-border px-3 py-2 font-mono text-[11.5px] transition-colors",
								file === current
									? "bg-sidebar text-foreground dark:bg-white/5"
									: "text-meta hover:text-foreground dark:text-panel-dim",
							)}
						>
							<FileTypeIcon path={file.path} className="size-3.5" />
							{file.path.split("/").pop() || "…"}
						</button>
					))}
				</div>
				{current && (
					<div className="flex min-h-0 flex-1 flex-col">
						<div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
							<span className="min-w-0 flex-1 truncate font-mono text-[12px] text-foreground">
								{current.path}
							</span>
							{isScriptPath(current.path) && (
								<span className="shrink-0 rounded-[4px] bg-petrol-tint px-1.5 py-px font-mono text-[9px] font-semibold tracking-[0.05em] text-petrol dark:bg-white/10">
									SCRIPT
								</span>
							)}
							<span className="shrink-0 font-mono text-[10.5px] text-meta dark:text-panel-dim">
								{formatBytes(skillFileSize(current))}
							</span>
						</div>
						{current.encoding === "base64" ? (
							<div className="flex flex-1 items-center justify-center bg-panel p-8 text-center text-[13px] text-panel-dim">
								Binary file — {formatBytes(skillFileSize(current))}.
							</div>
						) : (
							// The dark panel the login showcase and the landing terminal
							// use: code here is read, not edited, and it reads as the
							// same surface in either app theme.
							<div className="min-h-[260px] flex-1 overflow-auto bg-panel [scrollbar-width:thin]">
								<CodeBlock
									code={current.content}
									language={skillFileLanguage(current.path)}
									theme={PETROL_MONO_THEME}
									className="rounded-none"
								/>
							</div>
						)}
					</div>
				)}
			</div>
		</div>
	);
}

function Heading({ count, skill }: { count: number; skill?: Skill }) {
	return (
		<div className="mb-3 flex min-h-[24px] shrink-0 flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
			<span className="flex items-center gap-2">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
					FILES <span className="tracking-normal text-meta dark:text-panel-dim">{count}</span>
				</span>
			</span>
			{skill?.sourceId && (
				<span className="truncate font-mono text-[10.5px] text-meta dark:text-panel-dim">
					<Link href="/skills?view=sources" className="font-semibold text-petrol hover:underline">
						{skill.sourceName ?? "repository"}
					</Link>
					{skill.sourceRevision ? ` · ${shortRevision(skill.sourceRevision)}` : ""}
				</span>
			)}
		</div>
	);
}

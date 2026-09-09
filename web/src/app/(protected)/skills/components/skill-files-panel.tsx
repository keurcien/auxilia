"use client";

import { useRef, useState } from "react";
import { FileCode2, Plus, Trash2, Upload } from "lucide-react";
import type { SkillFile } from "@/types/skills";
import { cn } from "@/lib/utils";
import { formatBytes, readSkillFile, skillFileSize } from "../lib/skill-form";

interface SkillFilesPanelProps {
	files: SkillFile[];
	readOnly: boolean;
	onChange: (files: SkillFile[]) => void;
}

const PATH_PATTERN = /^[A-Za-z0-9_.\-/]+$/;

export function skillFilePathError(path: string, others: string[]): string | null {
	if (!path) return "A path is required";
	const parts = path.split("/");
	if (!PATH_PATTERN.test(path) || parts.some((p) => p === "" || p === "." || p === "..")) {
		return "Relative path, letters/digits/._-/ only, no empty or '..' segments";
	}
	if (parts[0].toLowerCase() === "skill.md") return "SKILL.md is the skill itself";
	if (others.some((other) => other.toLowerCase() === path.toLowerCase())) {
		return "Another file already has this path";
	}
	return null;
}

/**
 * The supporting files of a skill: one tab per file, the selected one
 * editable (path + text), binaries shown as a placeholder. Uploads land in
 * `scripts/`, `references/` or `assets/` by kind; the path stays editable.
 */
export default function SkillFilesPanel({ files, readOnly, onChange }: SkillFilesPanelProps) {
	const [selected, setSelected] = useState(0);
	const input = useRef<HTMLInputElement>(null);
	const current = files[Math.min(selected, files.length - 1)];

	const update = (index: number, patch: Partial<SkillFile>) => {
		onChange(files.map((file, i) => (i === index ? { ...file, ...patch } : file)));
	};

	const add = (added: SkillFile[]) => {
		const taken = new Set(files.map((f) => f.path.toLowerCase()));
		const fresh = added.map((file) => {
			let path = file.path;
			let n = 2;
			while (taken.has(path.toLowerCase())) {
				path = file.path.replace(/(\.[^./]+)?$/, `-${n}$1`);
				n += 1;
			}
			taken.add(path.toLowerCase());
			return { ...file, path };
		});
		onChange([...files, ...fresh]);
		setSelected(files.length);
	};

	const remove = (index: number) => {
		onChange(files.filter((_, i) => i !== index));
		setSelected(Math.max(0, index - 1));
	};

	const pathError = current
		? skillFilePathError(
				current.path,
				files.filter((f) => f !== current).map((f) => f.path),
			)
		: null;

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="mb-3 flex min-h-[24px] shrink-0 items-center justify-between">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
					FILES{" "}
					<span className="tracking-normal text-meta dark:text-panel-dim">{files.length}</span>
				</span>
				{!readOnly && (
					<div className="flex items-center gap-3">
						<input
							ref={input}
							type="file"
							multiple
							className="hidden"
							onChange={(e) => {
								const picked = Array.from(e.target.files ?? []);
								e.target.value = "";
								if (picked.length === 0) return;
								void Promise.all(picked.map(readSkillFile)).then(add);
							}}
						/>
						<button
							type="button"
							className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80"
							onClick={() => {
								input.current?.click();
							}}
						>
							<Upload className="size-3" />
							Upload
						</button>
						<button
							type="button"
							className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80"
							onClick={() => {
								add([{ path: "scripts/new-script.py", content: "", encoding: "utf-8" }]);
							}}
						>
							<Plus className="size-3" />
							New file
						</button>
					</div>
				)}
			</div>

			{files.length === 0 ? (
				<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
					No supporting files. Scripts, references and assets the skill needs go
					here, next to SKILL.md.
				</div>
			) : (
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
								<FileCode2 className="size-3" />
								{file.path.split("/").pop() || "…"}
							</button>
						))}
					</div>
					{current && (
						<div className="flex min-h-0 flex-1 flex-col">
							<div className="flex shrink-0 items-center gap-2 border-b border-border px-3 py-2">
								<input
									type="text"
									value={current.path}
									disabled={readOnly}
									spellCheck={false}
									onChange={(e) => {
										update(files.indexOf(current), { path: e.target.value.trim() });
									}}
									className={cn(
										"min-w-0 flex-1 bg-transparent font-mono text-[12px] text-foreground outline-none disabled:cursor-default",
										pathError && "text-destructive",
									)}
								/>
								<span className="shrink-0 font-mono text-[10.5px] text-meta dark:text-panel-dim">
									{formatBytes(skillFileSize(current))}
								</span>
								{!readOnly && (
									<button
										type="button"
										aria-label="Remove file"
										className="cursor-pointer rounded p-1 text-meta transition-colors hover:text-destructive"
										onClick={() => {
											remove(files.indexOf(current));
										}}
									>
										<Trash2 className="size-3.5" />
									</button>
								)}
							</div>
							{pathError && (
								<div className="border-b border-border px-3 py-1.5 text-[11.5px] text-destructive">
									{pathError}
								</div>
							)}
							{current.encoding === "base64" ? (
								<div className="flex flex-1 items-center justify-center p-8 text-center text-[13px] text-meta dark:text-panel-dim">
									Binary file — {formatBytes(skillFileSize(current))}. Uploaded as-is;
									replace it by removing and uploading again.
								</div>
							) : (
								<textarea
									value={current.content}
									readOnly={readOnly}
									spellCheck={false}
									onChange={(e) => {
										update(files.indexOf(current), { content: e.target.value });
									}}
									className="min-h-[260px] w-full flex-1 resize-none bg-transparent p-4 font-mono text-[12.5px] leading-[1.7] text-foreground outline-none [scrollbar-width:thin]"
								/>
							)}
						</div>
					)}
				</div>
			)}
		</div>
	);
}

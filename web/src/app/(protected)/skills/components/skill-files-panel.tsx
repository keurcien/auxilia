"use client";

import { useEffect, useRef, useState } from "react";
import { FileCode2, Plus, Trash2, Upload } from "lucide-react";
import { SkillFile } from "@/types/skills";
import { cn } from "@/lib/utils";
import { readUploadedFile } from "../lib/skill-form";

interface SkillFilesPanelProps {
	files: SkillFile[];
	readOnly: boolean;
	busy?: boolean;
	onChange: (update: (files: SkillFile[]) => SkillFile[]) => void;
	onError: (message: string) => void;
}

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

const fieldInputClass =
	"w-full rounded-lg border border-input bg-card px-3 py-[7px] font-mono text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default";

function formatBytes(base64: string): string {
	const bytes = Math.floor((base64.length * 3) / 4);
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Right panel of the skill editor: one horizontally scrollable tab per
 * supporting file, with the selected file's path and contents below.
 */
export default function SkillFilesPanel({
	files,
	readOnly,
	busy = false,
	onChange,
	onError,
}: SkillFilesPanelProps) {
	const [requested, setSelected] = useState(0);
	const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
	const fileInputRef = useRef<HTMLInputElement>(null);

	// Clamp rather than sync: removing the last file selects its neighbour
	// without an extra render.
	const selected = Math.max(0, Math.min(requested, files.length - 1));

	// Reveal a tab that was just added off the end of the strip.
	useEffect(() => {
		tabRefs.current[selected]?.scrollIntoView({
			block: "nearest",
			inline: "nearest",
		});
	}, [selected, files.length]);

	const current = files[selected];
	const editable = !readOnly && !busy;

	const updateCurrent = (patch: Partial<SkillFile>) => {
		onChange((prev) =>
			prev.map((f, i) => (i === selected ? { ...f, ...patch } : f)),
		);
	};

	const addBlank = () => {
		const taken = new Set(files.map((f) => f.path));
		let path = "scripts/script.py";
		for (let n = 2; taken.has(path); n++) path = `scripts/script-${n}.py`;
		onChange((prev) => [...prev, { path, content: "", encoding: "utf-8" }]);
		setSelected(files.length);
	};

	const upload = async (file: File) => {
		if (file.size > MAX_UPLOAD_BYTES) {
			onError("Files must be under 10 MB");
			return;
		}
		try {
			const value = await readUploadedFile(file);
			onChange((prev) => [...prev, value]);
			setSelected(files.length);
		} catch {
			onError("Could not read file");
		}
	};

	const removeCurrent = () => {
		onChange((prev) => prev.filter((_, i) => i !== selected));
	};

	return (
		<section className="flex min-h-0 flex-1 flex-col">
			<div className="mb-2.5 flex min-h-[30px] items-center justify-between gap-2">
				<label className="font-mono text-[10.5px] font-semibold uppercase tracking-[0.09em] text-subtle dark:text-panel-dim">
					Files
					<span className="ml-1.5 text-meta dark:text-panel-dim">
						{files.length}
					</span>
				</label>
				{!readOnly && (
					<div className="flex items-center gap-1.5">
						<button
							type="button"
							disabled={busy}
							onClick={() => {
								fileInputRef.current?.click();
							}}
							className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-2.5 py-1.5 text-[12px] font-semibold text-foreground transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50"
						>
							<Upload className="size-3" />
							Upload
						</button>
						<button
							type="button"
							disabled={busy}
							onClick={addBlank}
							className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-2.5 py-1.5 text-[12px] font-semibold text-petrol transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50"
						>
							<Plus className="size-3" />
							New file
						</button>
						<input
							ref={fileInputRef}
							type="file"
							className="sr-only"
							disabled={busy}
							onChange={(e) => {
								const f = e.target.files?.[0];
								if (f) void upload(f);
								e.target.value = "";
							}}
						/>
					</div>
				)}
			</div>
			<p className="mb-4 text-[12.5px] leading-[1.6] text-muted-foreground">
				Scripts, references and assets shipped with the skill. The agent reads
				text files on demand; scripts run inside a connected sandbox.
			</p>

			{files.length === 0 ? (
				<div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
					<FileCode2 className="mx-auto size-5 text-meta dark:text-panel-dim" />
					<p className="mt-3 text-[13px] font-medium text-foreground">
						No files yet
					</p>
					<p className="mt-1 text-[12.5px] text-muted-foreground">
						{readOnly
							? "This skill is instructions only."
							: "Add a script or upload a reference file."}
					</p>
				</div>
			) : (
				<div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card">
					{/* Tab strip: one tab per file, scrolls sideways instead of wrapping. */}
					<div
						role="tablist"
						aria-label="Skill files"
						className="flex shrink-0 gap-0.5 overflow-x-auto border-b border-border px-2 [scrollbar-width:thin]"
					>
						{files.map((file, i) => {
							const active = i === selected;
							return (
								<button
									key={i}
									ref={(el) => {
										tabRefs.current[i] = el;
									}}
									type="button"
									role="tab"
									aria-selected={active}
									title={file.path}
									onClick={() => {
										setSelected(i);
									}}
									className={cn(
										"-mb-px flex shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2.5 font-mono text-[12px] transition-colors",
										active
											? "border-petrol font-semibold text-foreground"
											: "border-transparent text-muted-foreground hover:text-foreground",
									)}
								>
									<FileCode2 className="size-3 shrink-0" />
									<span className="max-w-[200px] truncate">
										{file.path.split("/").pop() || file.path || "untitled"}
									</span>
								</button>
							);
						})}
					</div>

					{current && (
						<div className="flex min-h-0 flex-1 flex-col gap-3 p-4">
							<div className="flex items-center gap-2">
								{readOnly ? (
									<span className="flex-1 truncate font-mono text-[12.5px] text-foreground">
										{current.path}
									</span>
								) : (
									<input
										type="text"
										aria-label="File path"
										value={current.path}
										disabled={busy}
										spellCheck={false}
										placeholder="scripts/check.py"
										onChange={(e) => {
											updateCurrent({ path: e.target.value });
										}}
										className={fieldInputClass}
									/>
								)}
								{!readOnly && (
									<button
										type="button"
										title="Remove file"
										aria-label="Remove file"
										disabled={busy}
										onClick={removeCurrent}
										className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-destructive/10 hover:text-destructive disabled:cursor-not-allowed disabled:opacity-50"
									>
										<Trash2 className="size-3.5" />
									</button>
								)}
							</div>
							{current.encoding === "utf-8" ? (
								<textarea
									aria-label={`Contents of ${current.path}`}
									value={current.content}
									disabled={!editable}
									spellCheck={false}
									placeholder="# File contents"
									onChange={(e) => {
										updateCurrent({ content: e.target.value });
									}}
									className="min-h-[280px] w-full flex-1 resize-none rounded-lg border border-input bg-sidebar p-4 font-mono text-[12.5px] leading-[1.7] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default [scrollbar-width:thin]"
								/>
							) : (
								<div className="flex min-h-[160px] flex-1 flex-col items-center justify-center rounded-lg border border-border bg-sidebar p-6 text-center">
									<p className="text-[13px] font-medium text-foreground">
										Binary file
									</p>
									<p className="mt-1 font-mono text-[11.5px] text-meta dark:text-panel-dim">
										{formatBytes(current.content)} · available to the agent in
										the sandbox
									</p>
								</div>
							)}
						</div>
					)}
				</div>
			)}
		</section>
	);
}

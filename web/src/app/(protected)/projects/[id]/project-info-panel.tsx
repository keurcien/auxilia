"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
	CircleAlert,
	FilePlus2,
	FileText,
	Loader2,
	Search,
	Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { Checkbox } from "@/components/ui/checkbox";
import { SkillAvatar } from "@/components/ui/skill-avatar";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { formatBytes } from "@/app/(protected)/skills/lib/skill-form";
import { useUnsavedChangesWarning } from "@/hooks/use-unsaved-changes-warning";
import { getApiErrorMessage, toApiError } from "@/lib/api/errors";
import * as projectsApi from "@/lib/api/resources/projects";
import {
	audienceContains,
	incompatibleSkillReason,
} from "@/lib/resource-visibility";
import { cn } from "@/lib/utils";
import { useProjectsStore } from "@/stores/projects-store";
import { useSkillsStore } from "@/stores/skills-store";
import type {
	ProjectContextFile,
	ProjectDetail,
} from "@/types/projects";

type InfoTab = "prompt" | "context" | "skills";
type DirtyHandler = (dirty: boolean) => void;

const fieldClass =
	"w-full rounded-[9px] border border-input bg-card px-3 text-[13px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-not-allowed disabled:opacity-60";

function PanelActions({
	dirty,
	saving,
	disabled,
	onDiscard,
	onSave,
}: {
	dirty: boolean;
	saving: boolean;
	disabled: boolean;
	onDiscard: () => void;
	onSave: () => void;
}) {
	return (
		<div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
			<button
				type="button"
				disabled={!dirty || saving}
				onClick={onDiscard}
				className="cursor-pointer whitespace-nowrap rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12px] font-semibold text-foreground transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-45"
			>
				Discard
			</button>
			<button
				type="button"
				disabled={disabled || !dirty || saving}
				onClick={onSave}
				className="flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] bg-petrol px-3 py-1.5 text-[12px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-45"
			>
				{saving && <Loader2 className="size-3.5 animate-spin" />}
				{saving ? "Saving…" : "Save"}
			</button>
		</div>
	);
}

function SystemPromptPanel({
	detail,
	onDirtyChange,
}: {
	detail: ProjectDetail;
	onDirtyChange: DirtyHandler;
}) {
	const updateConfig = useProjectsStore((state) => state.updateProjectConfig);
	const refreshDetail = useProjectsStore(
		(state) => state.refreshProjectDetail,
	);
	const [draft, setDraft] = useState(detail.systemPrompt);
	const [basePrompt, setBasePrompt] = useState(detail.systemPrompt);
	const [revision, setRevision] = useState(detail.revision);
	const [saving, setSaving] = useState(false);
	const [remote, setRemote] = useState<{
		systemPrompt: string;
		revision: number;
	} | null>(null);
	const dirty = draft !== basePrompt;

	useEffect(() => {
		onDirtyChange(dirty);
	}, [dirty, onDirtyChange]);

	useEffect(() => {
		if (saving) return;
		if (
			detail.systemPrompt === basePrompt &&
			detail.revision === revision
		) {
			return;
		}
		queueMicrotask(() => {
			if (detail.systemPrompt === basePrompt) {
				setRevision(detail.revision);
				return;
			}
			if (dirty) {
				setRemote({
					systemPrompt: detail.systemPrompt,
					revision: detail.revision,
				});
				return;
			}
			setDraft(detail.systemPrompt);
			setBasePrompt(detail.systemPrompt);
			setRevision(detail.revision);
			setRemote(null);
		});
	}, [
		basePrompt,
		detail.revision,
		detail.systemPrompt,
		dirty,
		revision,
		saving,
	]);

	const save = async () => {
		if (!detail.canManage || !dirty || saving) return;
		setSaving(true);
		try {
			const updated = await updateConfig(detail.id, {
				systemPrompt: draft,
				revision,
			});
			setBasePrompt(updated.systemPrompt);
			setDraft(updated.systemPrompt);
			setRevision(updated.revision);
			setRemote(null);
			toast.success("System prompt saved.");
		} catch (error) {
			if (toApiError(error).status === 409) {
				toast.error(
					"The project changed elsewhere. Review the latest version before discarding your draft.",
				);
				try {
					const fresh = await refreshDetail(detail.id);
					setRemote({
						systemPrompt: fresh.systemPrompt,
						revision: fresh.revision,
					});
				} catch {
					toast.error("The latest project could not be loaded.");
				}
			} else {
				toast.error(
					getApiErrorMessage(error, "The system prompt could not be saved."),
				);
			}
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="min-h-0 flex-1 overflow-y-auto p-4">
				{remote && (
					<div className="mb-3 rounded-[9px] border border-warning/25 bg-warning-bg px-3 py-2.5">
						<div className="flex items-start gap-2">
							<CircleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />
							<p className="text-[11px] leading-4 text-warning">
								The system prompt changed elsewhere. Your draft is preserved.
							</p>
						</div>
						<button
							type="button"
							onClick={() => {
								setDraft(remote.systemPrompt);
								setBasePrompt(remote.systemPrompt);
								setRevision(remote.revision);
								setRemote(null);
							}}
							className="mt-2 cursor-pointer whitespace-nowrap text-[11px] font-semibold text-warning underline-offset-2 hover:underline"
						>
							Discard draft and reload
						</button>
					</div>
				)}
				<div className="mb-3">
					<h3 className="text-[13px] font-semibold text-foreground">
						Project instructions
					</h3>
					<p className="mt-1 text-[11.5px] leading-5 text-meta dark:text-panel-dim">
						Applied to every conversation and trigger in this project.
					</p>
				</div>
				<textarea
					value={draft}
					readOnly={!detail.canManage}
					onChange={(event) => {
						setDraft(event.target.value);
					}}
					placeholder="Describe the project, its goals, constraints, and working conventions."
					className={cn(
						fieldClass,
						"min-h-[280px] resize-y py-3 font-mono text-[12px] leading-5",
					)}
				/>
				{!detail.canManage && (
					<p className="mt-2 text-[11px] text-meta dark:text-panel-dim">
						You have read-only access to this project.
					</p>
				)}
			</div>
			{detail.canManage && (
				<PanelActions
					dirty={dirty}
					saving={saving}
					disabled={false}
					onDiscard={() => {
						if (remote) {
							setDraft(remote.systemPrompt);
							setBasePrompt(remote.systemPrompt);
							setRevision(remote.revision);
							setRemote(null);
						} else {
							setDraft(basePrompt);
						}
					}}
					onSave={() => {
						void save();
					}}
				/>
			)}
		</div>
	);
}

function ContextPanel({
	detail,
	onDirtyChange,
}: {
	detail: ProjectDetail;
	onDirtyChange: DirtyHandler;
}) {
	const confirm = useConfirmDialog();
	const getFile = useProjectsStore((state) => state.getContextFile);
	const createFile = useProjectsStore((state) => state.createContextFile);
	const updateFile = useProjectsStore((state) => state.updateContextFile);
	const deleteFile = useProjectsStore((state) => state.deleteContextFile);
	const refreshDetail = useProjectsStore(
		(state) => state.refreshProjectDetail,
	);
	const [selectedId, setSelectedId] = useState<string | null>(
		detail.contextFiles[0]?.id ?? null,
	);
	const [loaded, setLoaded] = useState<ProjectContextFile | null>(null);
	const [path, setPath] = useState("");
	const [content, setContent] = useState("");
	const [loading, setLoading] = useState(false);
	const [saving, setSaving] = useState(false);
	const [remoteState, setRemoteState] = useState<
		| { kind: "changed"; file: ProjectContextFile }
		| { kind: "deleted" }
		| null
	>(null);
	const creating = selectedId === null && loaded === null;
	const dirty =
		creating
			? path.length > 0 || content.length > 0
			: loaded !== null &&
				(path !== loaded.path || content !== loaded.content);

	useEffect(() => {
		onDirtyChange(dirty);
	}, [dirty, onDirtyChange]);

	useEffect(() => {
		if (saving || !selectedId || !loaded) return;
		const summary = detail.contextFiles.find((file) => file.id === selectedId);
		if (!summary) {
			if (remoteState?.kind === "deleted") return;
			queueMicrotask(() => {
				if (dirty) {
					setRemoteState({ kind: "deleted" });
					return;
				}
				setSelectedId(detail.contextFiles[0]?.id ?? null);
				setLoaded(null);
				setRemoteState(null);
			});
			return;
		}
		if (
			summary.revision === loaded.revision ||
			(remoteState?.kind === "changed" &&
				remoteState.file.revision === summary.revision)
		) {
			return;
		}
		let cancelled = false;
		void getFile(selectedId)
			.then((fresh) => {
				if (cancelled) return;
				if (dirty) {
					setRemoteState({ kind: "changed", file: fresh });
				} else {
					setLoaded(fresh);
					setPath(fresh.path);
					setContent(fresh.content);
					setRemoteState(null);
				}
			})
			.catch((error: unknown) => {
				if (!cancelled && toApiError(error).status === 404) {
					setRemoteState({ kind: "deleted" });
				}
			});
		return () => {
			cancelled = true;
		};
	}, [
		detail.contextFiles,
		dirty,
		getFile,
		loaded,
		remoteState,
		saving,
		selectedId,
	]);

	useEffect(() => {
		if (!selectedId) return;
		let cancelled = false;
		setLoading(true);
		void getFile(selectedId)
			.then((file) => {
				if (cancelled) return;
				setLoaded(file);
				setPath(file.path);
				setContent(file.content);
				setRemoteState(null);
			})
			.catch((error: unknown) => {
				if (!cancelled) {
					toast.error(
						getApiErrorMessage(error, "The context file could not be loaded."),
					);
				}
			})
			.finally(() => {
				if (!cancelled) setLoading(false);
			});
		return () => {
			cancelled = true;
		};
	}, [getFile, selectedId]);

	const choose = (id: string) => {
		if (id === selectedId) return;
		if (dirty && !window.confirm("Discard the unsaved context file changes?")) {
			return;
		}
		setSelectedId(id);
		setLoaded(null);
		setRemoteState(null);
	};

	const startNew = () => {
		if (dirty && !window.confirm("Discard the unsaved context file changes?")) {
			return;
		}
		setSelectedId(null);
		setLoaded(null);
		setPath("context.md");
		setContent("");
		setRemoteState(null);
	};

	const save = async () => {
		if (!detail.canManage || saving || !path.trim()) return;
		setSaving(true);
		try {
			const file = loaded
				? await updateFile(loaded.id, {
						path: path.trim(),
						content,
						revision: loaded.revision,
					})
				: await createFile(detail.id, { path: path.trim(), content });
			setSelectedId(file.id);
			setLoaded(file);
			setPath(file.path);
			setContent(file.content);
			setRemoteState(null);
			toast.success(loaded ? "Context file saved." : "Context file created.");
		} catch (error) {
			const apiError = toApiError(error);
			if (
				loaded &&
				apiError.status === 409 &&
				apiError.detail?.includes("changed since you opened it")
			) {
				toast.error(
					"This file changed elsewhere. Your draft is preserved until you choose what to do.",
				);
				try {
					const fresh = await getFile(loaded.id);
					setRemoteState({ kind: "changed", file: fresh });
					await refreshDetail(detail.id);
				} catch (loadError) {
					if (toApiError(loadError).status === 404) {
						setRemoteState({ kind: "deleted" });
					} else {
						toast.error("The latest context file could not be loaded.");
					}
				}
			} else {
				toast.error(
					getApiErrorMessage(error, "The context file could not be saved."),
				);
			}
		} finally {
			setSaving(false);
		}
	};

	const remove = async () => {
		if (!loaded || !detail.canManage || saving) return;
		const accepted = await confirm({
			title: `Delete ${loaded.path}?`,
			description: "This context file will be removed permanently.",
			confirmLabel: "Delete file",
			destructive: true,
		});
		if (!accepted) return;
		setSaving(true);
		try {
			await deleteFile(detail.id, loaded.id, loaded.revision);
			const next = detail.contextFiles.find((file) => file.id !== loaded.id);
			setSelectedId(next?.id ?? null);
			setLoaded(null);
			setRemoteState(null);
			if (!next) {
				setPath("");
				setContent("");
			}
			toast.success("Context file deleted.");
		} catch (error) {
			if (toApiError(error).status === 409) {
				toast.error(
					"This file changed elsewhere. Review the latest version before deleting it.",
				);
				try {
					const fresh = await getFile(loaded.id);
					setRemoteState({ kind: "changed", file: fresh });
					await refreshDetail(detail.id);
				} catch (loadError) {
					if (toApiError(loadError).status === 404) {
						setRemoteState({ kind: "deleted" });
					}
				}
			} else {
				toast.error(
					getApiErrorMessage(error, "The context file could not be deleted."),
				);
			}
		} finally {
			setSaving(false);
		}
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex min-h-0 flex-1 flex-col lg:flex-row">
				<div className="max-h-44 shrink-0 overflow-y-auto border-b border-border bg-sidebar/45 p-2 lg:max-h-none lg:w-40 lg:border-b-0 lg:border-r">
					{detail.canManage && (
						<button
							type="button"
							onClick={startNew}
							className="mb-1 flex h-8 w-full cursor-pointer items-center gap-2 whitespace-nowrap rounded-[6px] px-2 text-left text-[11.5px] font-semibold text-petrol transition-colors hover:bg-petrol-tint dark:text-panel-terminal dark:hover:bg-white/5"
						>
							<FilePlus2 className="size-3.5" />
							New file
						</button>
					)}
					{detail.contextFiles.map((file) => (
						<button
							key={file.id}
							type="button"
							onClick={() => {
								choose(file.id);
							}}
							className={cn(
								"flex w-full cursor-pointer items-start gap-2 rounded-[6px] px-2 py-2 text-left transition-colors hover:bg-hover",
								selectedId === file.id && "bg-petrol-tint dark:bg-white/10",
							)}
						>
							<FileText className="mt-0.5 size-3.5 shrink-0 text-petrol dark:text-panel-terminal" />
							<span className="min-w-0">
								<span className="block truncate text-[11.5px] font-medium text-foreground">
									{file.path}
								</span>
								<span className="mt-0.5 block font-mono text-[9.5px] text-meta">
									{formatBytes(file.size)}
								</span>
							</span>
						</button>
					))}
					{detail.contextFiles.length === 0 && !creating && (
						<p className="px-2 py-5 text-center text-[11px] text-meta">
							No context files
						</p>
					)}
				</div>
				<div className="flex min-h-[340px] min-w-0 flex-1 flex-col p-4">
					{remoteState && (
						<div className="mb-3 rounded-[9px] border border-warning/25 bg-warning-bg px-3 py-2.5">
							<div className="flex items-start gap-2">
								<CircleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />
								<p className="text-[11px] leading-4 text-warning">
									{remoteState.kind === "changed"
										? "This file changed elsewhere. Your draft is preserved."
										: "This file was deleted elsewhere. Your draft is preserved."}
								</p>
							</div>
							<div className="mt-2 flex flex-wrap items-center gap-3">
								{remoteState.kind === "changed" ? (
									<button
										type="button"
										onClick={() => {
											setLoaded(remoteState.file);
											setPath(remoteState.file.path);
											setContent(remoteState.file.content);
											setRemoteState(null);
										}}
										className="cursor-pointer whitespace-nowrap text-[11px] font-semibold text-warning underline-offset-2 hover:underline"
									>
										Discard draft and reload
									</button>
								) : (
									<>
										<button
											type="button"
											onClick={() => {
												const next = detail.contextFiles[0];
												setSelectedId(next?.id ?? null);
												setLoaded(null);
												setPath("");
												setContent("");
												setRemoteState(null);
											}}
											className="cursor-pointer whitespace-nowrap text-[11px] font-semibold text-warning underline-offset-2 hover:underline"
										>
											Discard draft
										</button>
										<button
											type="button"
											onClick={() => {
												setSelectedId(null);
												setLoaded(null);
												setRemoteState(null);
											}}
											className="cursor-pointer whitespace-nowrap text-[11px] font-semibold text-warning underline-offset-2 hover:underline"
										>
											Keep as a new file
										</button>
									</>
								)}
							</div>
						</div>
					)}
					{loading ? (
						<div className="flex flex-1 items-center justify-center text-meta">
							<Loader2 className="size-5 animate-spin" />
						</div>
					) : loaded || creating ? (
						<>
							<div className="flex items-center gap-2">
								<input
									value={path}
									readOnly={!detail.canManage}
									onChange={(event) => {
										setPath(event.target.value);
									}}
									aria-label="Context file path"
									placeholder="folder/context.md"
									className={cn(fieldClass, "h-9 min-w-0 flex-1 font-mono")}
								/>
								{loaded && detail.canManage && (
									<button
										type="button"
										aria-label={`Delete ${loaded.path}`}
										onClick={() => {
											void remove();
										}}
										className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-[7px] border border-destructive/20 text-destructive transition-colors hover:bg-destructive/8"
									>
										<Trash2 className="size-3.5" />
									</button>
								)}
							</div>
							<div className="mt-2 flex items-center justify-between text-[10px] text-meta">
								<span>Markdown</span>
								<span className="font-mono">
									{formatBytes(new TextEncoder().encode(content).length)}
									{loaded ? ` / revision ${loaded.revision}` : ""}
								</span>
							</div>
							<textarea
								value={content}
								readOnly={!detail.canManage}
								onChange={(event) => {
									setContent(event.target.value);
								}}
								aria-label="Context file content"
								placeholder="# Project context"
								className={cn(
									fieldClass,
									"mt-3 min-h-[250px] flex-1 resize-none py-3 font-mono text-[12px] leading-5",
								)}
							/>
						</>
					) : (
						<div className="flex flex-1 flex-col items-center justify-center text-center">
							<FileText className="size-7 text-faint" />
							<p className="mt-3 text-[12.5px] font-semibold text-foreground">
								Select a context file
							</p>
							<p className="mt-1 max-w-52 text-[11px] leading-5 text-meta">
								Markdown files provide durable project knowledge.
							</p>
						</div>
					)}
				</div>
			</div>
			{detail.canManage && (loaded || creating) && (
				<PanelActions
					dirty={dirty}
					saving={saving}
					disabled={!path.trim() || !path.trim().endsWith(".md")}
					onDiscard={() => {
						if (remoteState?.kind === "changed") {
							setLoaded(remoteState.file);
							setPath(remoteState.file.path);
							setContent(remoteState.file.content);
							setRemoteState(null);
						} else if (remoteState?.kind === "deleted") {
							const next = detail.contextFiles[0];
							setSelectedId(next?.id ?? null);
							setLoaded(null);
							setPath("");
							setContent("");
							setRemoteState(null);
						} else if (loaded) {
							setPath(loaded.path);
							setContent(loaded.content);
						} else {
							setPath("");
							setContent("");
						}
					}}
					onSave={() => {
						void save();
					}}
				/>
			)}
		</div>
	);
}

const sameIds = (left: Set<string>, right: readonly string[]): boolean =>
	left.size === right.length && right.every((id) => left.has(id));

function SkillsPanel({
	detail,
	onDirtyChange,
}: {
	detail: ProjectDetail;
	onDirtyChange: DirtyHandler;
}) {
	const skills = useSkillsStore((state) => state.skills);
	const fetchSkills = useSkillsStore((state) => state.fetchSkills);
	const replaceSkills = useProjectsStore(
		(state) => state.replaceProjectSkills,
	);
	const [query, setQuery] = useState("");
	const [selected, setSelected] = useState(() => new Set(detail.skillIds));
	const [base, setBase] = useState(() => new Set(detail.skillIds));
	const [revision, setRevision] = useState(detail.revision);
	const [remote, setRemote] = useState<{
		skillIds: string[];
		revision: number;
	} | null>(null);
	const [saving, setSaving] = useState(false);

	useEffect(() => {
		void fetchSkills().catch((error: unknown) => {
			toast.error(getApiErrorMessage(error, "Skills could not be loaded."));
		});
	}, [fetchSkills]);

	const dirty =
		selected.size !== base.size || [...selected].some((id) => !base.has(id));

	useEffect(() => {
		onDirtyChange(dirty);
	}, [dirty, onDirtyChange]);

	useEffect(() => {
		if (saving) return;
		if (sameIds(base, detail.skillIds)) {
			if (revision !== detail.revision) {
				queueMicrotask(() => {
					setRevision(detail.revision);
				});
			}
			return;
		}
		queueMicrotask(() => {
			if (dirty) {
				setRemote({
					skillIds: detail.skillIds,
					revision: detail.revision,
				});
				return;
			}
			const next = new Set(detail.skillIds);
			setSelected(next);
			setBase(next);
			setRevision(detail.revision);
			setRemote(null);
		});
	}, [base, detail.revision, detail.skillIds, dirty, revision, saving]);

	const filtered = useMemo(() => {
		const needle = query.trim().toLocaleLowerCase();
		if (!needle) return skills;
		return skills.filter(
			(skill) =>
				skill.name.toLocaleLowerCase().includes(needle) ||
				skill.description.toLocaleLowerCase().includes(needle),
		);
	}, [query, skills]);

	const save = async () => {
		if (!detail.canManage || !dirty || saving) return;
		setSaving(true);
		try {
			const result = await replaceSkills(detail.id, [...selected], revision);
			setSelected(new Set(result.skillIds));
			setBase(new Set(result.skillIds));
			setRevision(result.revision);
			setRemote(null);
			toast.success("Project skills saved.");
		} catch (error) {
			if (toApiError(error).status === 409) {
				toast.error(
					"Project skills changed elsewhere. Your selection is preserved.",
				);
				try {
					const latest = await projectsApi.getProjectSkills(detail.id);
					setRemote(latest);
					await useProjectsStore
						.getState()
						.refreshProjectDetail(detail.id);
				} catch {
					toast.error("The latest project skills could not be loaded.");
				}
			} else {
				toast.error(
					getApiErrorMessage(error, "Project skills could not be saved."),
				);
			}
		} finally {
			setSaving(false);
		}
	};

	const incompatibleSelected = skills.some(
		(skill) =>
			selected.has(skill.id) &&
			!audienceContains(detail, skill),
	);

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="min-h-0 flex-1 overflow-y-auto p-4">
				{remote && (
					<div className="mb-3 rounded-[9px] border border-warning/25 bg-warning-bg px-3 py-2.5">
						<div className="flex items-start gap-2">
							<CircleAlert className="mt-0.5 size-3.5 shrink-0 text-warning" />
							<p className="text-[11px] leading-4 text-warning">
								Project skills changed elsewhere. Your selection is preserved.
							</p>
						</div>
						<button
							type="button"
							onClick={() => {
								const next = new Set(remote.skillIds);
								setSelected(next);
								setBase(next);
								setRevision(remote.revision);
								setRemote(null);
							}}
							className="mt-2 cursor-pointer whitespace-nowrap text-[11px] font-semibold text-warning underline-offset-2 hover:underline"
						>
							Discard selection and reload
						</button>
					</div>
				)}
				<p className="mb-3 text-[11.5px] leading-5 text-meta dark:text-panel-dim">
					The model selects relevant skills automatically. No slash command is
					needed.
				</p>
				<div className="relative">
					<Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-meta" />
					<input
						value={query}
						onChange={(event) => {
							setQuery(event.target.value);
						}}
						placeholder="Search skills"
						className={cn(fieldClass, "h-9 pl-9")}
					/>
				</div>
				<div className="mt-3 space-y-1">
					{filtered.map((skill) => {
						const checked = selected.has(skill.id);
						const compatible = audienceContains(detail, skill);
						return (
							<div
								key={skill.id}
								className={cn(
									"flex items-center gap-3 rounded-[8px] border px-3 py-2.5",
									checked
										? "border-petrol/25 bg-petrol-tint/70 dark:bg-white/5"
										: "border-transparent hover:bg-hover",
								)}
							>
								<Checkbox
									checked={checked}
									disabled={
										!detail.canManage || (!compatible && !checked)
									}
									aria-label={`${checked ? "Remove" : "Add"} ${skill.name}`}
									onCheckedChange={(next) => {
										setSelected((current) => {
											const updated = new Set(current);
											if (next) updated.add(skill.id);
											else updated.delete(skill.id);
											return updated;
										});
									}}
								/>
								<SkillAvatar
									skillId={skill.id}
									name={skill.name}
									emoji={skill.emoji}
									color={skill.color}
									imageRevision={skill.imageRevision}
									size="xs"
								/>
								<div className="min-w-0">
									<p className="truncate text-[12px] font-semibold text-foreground">
										{skill.name}
									</p>
									<p className="truncate text-[10.5px] text-meta">
										{compatible
											? skill.description
											: incompatibleSkillReason(detail, skill)}
									</p>
								</div>
							</div>
						);
					})}
					{filtered.length === 0 && (
						<p className="py-8 text-center text-[11.5px] text-meta">
							No skills match this search.
						</p>
					)}
				</div>
			</div>
			{detail.canManage && (
				<PanelActions
					dirty={dirty}
					saving={saving}
					disabled={incompatibleSelected}
					onDiscard={() => {
						if (remote) {
							const next = new Set(remote.skillIds);
							setSelected(next);
							setBase(next);
							setRevision(remote.revision);
							setRemote(null);
						} else {
							setSelected(new Set(base));
						}
					}}
					onSave={() => {
						void save();
					}}
				/>
			)}
		</div>
	);
}

export function ProjectInfoPanel({ detail }: { detail: ProjectDetail }) {
	const [tab, setTab] = useState<InfoTab>("prompt");
	const [dirtyPanels, setDirtyPanels] = useState<Record<InfoTab, boolean>>({
		prompt: false,
		context: false,
		skills: false,
	});
	const setPromptDirty = useCallback((dirty: boolean) => {
		setDirtyPanels((current) =>
			current.prompt === dirty ? current : { ...current, prompt: dirty },
		);
	}, []);
	const setContextDirty = useCallback((dirty: boolean) => {
		setDirtyPanels((current) =>
			current.context === dirty ? current : { ...current, context: dirty },
		);
	}, []);
	const setSkillsDirty = useCallback((dirty: boolean) => {
		setDirtyPanels((current) =>
			current.skills === dirty ? current : { ...current, skills: dirty },
		);
	}, []);
	const isDirty = Object.values(dirtyPanels).some(Boolean);
	useUnsavedChangesWarning(isDirty);

	return (
		<div className="flex h-full min-h-0 flex-col bg-sidebar/35">
			<div className="border-b border-border px-2 pt-1">
				<UnderlineTabs
					value={tab}
					onChange={setTab}
					idPrefix={`project-info-${detail.id}`}
					tabs={[
						{
							key: "prompt",
							label: "Instructions",
							alert: dirtyPanels.prompt ? "Unsaved changes" : undefined,
						},
						{
							key: "context",
							label: "Context",
							count: detail.contextFiles.length,
							alert: dirtyPanels.context ? "Unsaved changes" : undefined,
						},
						{
							key: "skills",
							label: "Skills",
							count: detail.skillIds.length,
							alert: dirtyPanels.skills ? "Unsaved changes" : undefined,
						},
					]}
				/>
			</div>
			<div
				id={`project-info-${detail.id}-panel-prompt`}
				role="tabpanel"
				aria-labelledby={`project-info-${detail.id}-tab-prompt`}
				hidden={tab !== "prompt"}
				className={cn("min-h-0 flex-1", tab !== "prompt" && "hidden")}
			>
				<SystemPromptPanel
					detail={detail}
					onDirtyChange={setPromptDirty}
				/>
			</div>
			<div
				id={`project-info-${detail.id}-panel-context`}
				role="tabpanel"
				aria-labelledby={`project-info-${detail.id}-tab-context`}
				hidden={tab !== "context"}
				className={cn("min-h-0 flex-1", tab !== "context" && "hidden")}
			>
				<ContextPanel detail={detail} onDirtyChange={setContextDirty} />
			</div>
			<div
				id={`project-info-${detail.id}-panel-skills`}
				role="tabpanel"
				aria-labelledby={`project-info-${detail.id}-tab-skills`}
				hidden={tab !== "skills"}
				className={cn("min-h-0 flex-1", tab !== "skills" && "hidden")}
			>
				<SkillsPanel detail={detail} onDirtyChange={setSkillsDirty} />
			</div>
		</div>
	);
}

"use client";

import {
	useEffect,
	useMemo,
	useRef,
	useState,
	useSyncExternalStore,
} from "react";
import EmojiPicker, { type EmojiClickData, Theme } from "emoji-picker-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import {
	AlarmClock,
	Check,
	CircleCheck,
	ChevronDown,
	ChevronRight,
	Folder,
	FolderInput,
	FolderPlus,
	Info,
	ListTree,
	Loader2,
	MoreVertical,
	PanelRight,
	Search,
	SquarePen,
	Trash2,
	Undo2,
	X,
} from "lucide-react";
import { toast } from "sonner";

import {
	HeaderButton,
	HeaderReadOnly,
	SubpageHeader,
} from "@/components/layout/subpage-header";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import { ConversationCompletionButton } from "@/components/layout/app-sidebar/conversation-completion-button";
import { FolderDialog } from "@/components/layout/app-sidebar/folder-dialog";
import {
	ThreadPlacementDialog,
	type ThreadPlacementTarget,
} from "@/components/layout/app-sidebar/thread-placement-dialog";
import {
	TriggerPlacementDialog,
	type TriggerPlacementTarget,
} from "@/components/layout/app-sidebar/trigger-placement-dialog";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	cancelPreparedNavigation,
	navigateWithUnsavedChanges,
	prepareToDiscardUnsavedChanges,
} from "@/hooks/use-unsaved-changes-warning";
import {
	getProjectFolderAncestors,
	normalizeProjectTree,
	PROJECT_ROOT,
} from "@/lib/project-folders";
import { cn } from "@/lib/utils";
import { useAgentsStore } from "@/stores/agents-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useWorkspacesStore } from "@/stores/workspaces-store";
import type {
	ProjectDetail,
	ProjectFolder,
	ProjectThread,
	ProjectTrigger,
} from "@/types/projects";
import type { ResourceVisibility } from "@/types/visibility";
import { ProjectInfoPanel } from "./project-info-panel";

type ProjectView = "directory" | "split";

type FolderDialogState = {
	folder: ProjectFolder | null;
	parentId: string | null;
} | null;

const viewStorageKey = (workspaceId: string, projectId: string) =>
	`auxilia:project-view:${workspaceId}:${projectId}`;

const LARGE_VIEWPORT = "(min-width: 1024px)";
const INFO_PANEL_WIDTH_STORAGE_KEY = "auxilia:project-info-panel-width";
const INFO_PANEL_MIN_WIDTH = 340;
const INFO_PANEL_DEFAULT_WIDTH = 470;

function clampInfoPanelWidth(width: number): number {
	if (typeof window === "undefined") return INFO_PANEL_DEFAULT_WIDTH;
	return Math.min(
		Math.max(width, INFO_PANEL_MIN_WIDTH),
		window.innerWidth * 0.45,
	);
}

function subscribeLargeViewport(onChange: () => void): () => void {
	const media = window.matchMedia(LARGE_VIEWPORT);
	media.addEventListener("change", onChange);
	return () => {
		media.removeEventListener("change", onChange);
	};
}

function largeViewportSnapshot(): boolean {
	return window.matchMedia(LARGE_VIEWPORT).matches;
}

function titleOf(thread: ProjectThread): string {
	return thread.title?.trim() || "Untitled conversation";
}

function ProjectIdentityHeading({ project }: { project: ProjectDetail }) {
	const { resolvedTheme } = useTheme();
	const updateProject = useProjectsStore((state) => state.updateProject);
	const [name, setName] = useState(project.name);
	const [emoji, setEmoji] = useState(project.emoji);
	const [pickerOpen, setPickerOpen] = useState(false);
	const [pending, setPending] = useState(0);
	const committedNameRef = useRef(project.name);
	const emojiTriggerRef = useRef<HTMLButtonElement>(null);
	const emojiPickerRef = useRef<HTMLDivElement>(null);

	useEffect(() => {
		setName(project.name);
		committedNameRef.current = project.name;
	}, [project.name]);

	useEffect(() => {
		setEmoji(project.emoji);
	}, [project.emoji]);

	useEffect(() => {
		if (!pickerOpen) return;
		const closeOnOutsidePointer = (event: PointerEvent) => {
			if (
				emojiPickerRef.current &&
				!emojiPickerRef.current.contains(event.target as Node)
			) {
				setPickerOpen(false);
			}
		};
		document.addEventListener("pointerdown", closeOnOutsidePointer);
		return () => {
			document.removeEventListener("pointerdown", closeOnOutsidePointer);
		};
	}, [pickerOpen]);

	const saveName = async () => {
		const next = name.trim();
		if (!next) {
			setName(committedNameRef.current);
			return;
		}
		if (next === committedNameRef.current) {
			if (next !== name) setName(next);
			return;
		}
		const previous = committedNameRef.current;
		committedNameRef.current = next;
		setName(next);
		setPending((value) => value + 1);
		try {
			await updateProject(project.id, { name: next });
		} catch (error) {
			committedNameRef.current = previous;
			setName(previous);
			toast.error(getApiErrorMessage(error, "The project name could not be saved."));
		} finally {
			setPending((value) => Math.max(0, value - 1));
		}
	};

	const saveEmoji = async (next: string | null) => {
		const previous = emoji;
		setEmoji(next);
		setPickerOpen(false);
		setPending((value) => value + 1);
		requestAnimationFrame(() => {
			emojiTriggerRef.current?.focus();
		});
		try {
			await updateProject(project.id, { emoji: next });
		} catch (error) {
			setEmoji(previous);
			toast.error(getApiErrorMessage(error, "The project icon could not be saved."));
		} finally {
			setPending((value) => Math.max(0, value - 1));
		}
	};

	if (!project.canManage) {
		return (
			<h1 className="flex min-w-0 items-center gap-2 font-display text-[20px] font-bold text-foreground">
				{project.emoji && (
					<span aria-hidden className="shrink-0 text-[19px]">
						{project.emoji}
					</span>
				)}
				<span className="truncate">{project.name}</span>
			</h1>
		);
	}

	return (
		<div className="flex min-w-0 items-center gap-1.5">
			<div ref={emojiPickerRef} className="relative shrink-0">
				<button
					ref={emojiTriggerRef}
					type="button"
					aria-label="Change project emoji"
					aria-expanded={pickerOpen}
					onPointerDown={(event) => {
						event.preventDefault();
					}}
					onKeyDown={(event) => {
						if (event.key === "Escape" && pickerOpen) {
							event.preventDefault();
							setPickerOpen(false);
							return;
						}
						if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
						event.preventDefault();
						setPickerOpen(true);
					}}
					onClick={() => {
						setPickerOpen((value) => !value);
					}}
					className="flex size-8 cursor-pointer items-center justify-center rounded-[7px] border border-transparent text-[18px] outline-none transition-colors hover:border-border hover:bg-card focus-visible:border-petrol focus-visible:ring-2 focus-visible:ring-ring/30"
				>
					{emoji ?? <Folder className="size-4 text-petrol" />}
				</button>
				{pickerOpen && (
					<div className="absolute left-0 top-full z-[60] mt-2 overflow-hidden rounded-[10px] border border-border bg-card shadow-xl">
						{emoji && (
							<button
								type="button"
								onClick={() => {
									void saveEmoji(null);
								}}
								className="flex h-9 w-full cursor-pointer items-center gap-2 border-b border-border px-3 text-left text-[11.5px] font-semibold text-label transition-colors hover:bg-hover dark:hover:bg-white/10"
							>
								<Folder className="size-3.5 text-petrol" />
								Use folder icon
							</button>
						)}
						<EmojiPicker
							autoFocusSearch
							onEmojiClick={(data: EmojiClickData) => {
								void saveEmoji(data.emoji);
							}}
							theme={resolvedTheme === "dark" ? Theme.DARK : Theme.LIGHT}
							skinTonesDisabled
							previewConfig={{ showPreview: false }}
						/>
					</div>
				)}
			</div>
			<input
				value={name}
				maxLength={255}
				aria-label="Project name"
				onChange={(event) => {
					setName(event.target.value);
				}}
				onBlur={() => {
					void saveName();
				}}
				onKeyDown={(event) => {
					if (event.key === "Enter") {
						event.preventDefault();
						event.currentTarget.blur();
					}
					if (event.key === "Escape") {
						event.preventDefault();
						setName(committedNameRef.current);
						event.currentTarget.blur();
					}
				}}
				className="-ml-1 h-8 min-w-0 flex-1 rounded-[7px] border border-transparent bg-transparent px-1 font-display text-[20px] font-bold text-foreground outline-none transition-colors hover:border-border focus:border-petrol focus:bg-card"
			/>
			{pending > 0 && (
				<Loader2
					aria-label="Saving project identity"
					className="size-3.5 shrink-0 animate-spin text-meta"
				/>
			)}
		</div>
	);
}

function ProjectDescription({ project }: { project: ProjectDetail }) {
	const updateProject = useProjectsStore((state) => state.updateProject);
	const [description, setDescription] = useState(project.description);
	const [saving, setSaving] = useState(false);
	const committedDescriptionRef = useRef(project.description);
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	useEffect(() => {
		setDescription(project.description);
		committedDescriptionRef.current = project.description;
	}, [project.description]);

	useEffect(() => {
		const textarea = textareaRef.current;
		if (!textarea) return;
		textarea.style.height = "0px";
		textarea.style.height = `${textarea.scrollHeight}px`;
	}, [description]);

	const saveDescription = async () => {
		const next = description.trim();
		if (next === committedDescriptionRef.current) {
			if (next !== description) setDescription(next);
			return;
		}
		const previous = committedDescriptionRef.current;
		committedDescriptionRef.current = next;
		setDescription(next);
		setSaving(true);
		try {
			await updateProject(project.id, { description: next });
		} catch (error) {
			committedDescriptionRef.current = previous;
			setDescription(previous);
			toast.error(
				getApiErrorMessage(error, "The project description could not be saved."),
			);
		} finally {
			setSaving(false);
		}
	};

	if (!project.canManage) {
		return project.description ? (
			<p className="mt-2 max-w-2xl whitespace-pre-wrap text-[12px] leading-5 text-label">
				{project.description}
			</p>
		) : null;
	}

	return (
		<div className="relative mt-1.5 w-full sm:w-1/2">
			<textarea
				ref={textareaRef}
				rows={1}
				maxLength={4_000}
				value={description}
				aria-label="Project description"
				placeholder="Add a project description"
				onChange={(event) => {
					setDescription(event.target.value);
				}}
				onBlur={() => {
					void saveDescription();
				}}
				onKeyDown={(event) => {
					if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
						event.preventDefault();
						event.currentTarget.blur();
					}
					if (event.key === "Escape") {
						event.preventDefault();
						setDescription(committedDescriptionRef.current);
						event.currentTarget.blur();
					}
				}}
				className="-ml-1 block w-full resize-none overflow-hidden rounded-[7px] border border-transparent bg-transparent py-0.5 pl-1 pr-6 text-[12px] leading-5 text-label outline-none transition-colors placeholder:text-meta hover:border-border focus:border-petrol focus:bg-card"
			/>
			{saving && (
				<Loader2
					aria-label="Saving project description"
					className="absolute right-1 top-1 size-3.5 animate-spin text-meta"
				/>
			)}
		</div>
	);
}

function ProjectVisibilityEditor({ project }: { project: ProjectDetail }) {
	const updateProject = useProjectsStore((state) => state.updateProject);
	const [visibility, setVisibility] = useState(project.visibility);
	const [teamIds, setTeamIds] = useState(project.teamIds);
	const [saving, setSaving] = useState(false);
	const committedRef = useRef({
		visibility: project.visibility,
		teamIds: project.teamIds,
	});
	const saveVersionRef = useRef(0);

	useEffect(() => {
		setVisibility(project.visibility);
		setTeamIds(project.teamIds);
		committedRef.current = {
			visibility: project.visibility,
			teamIds: project.teamIds,
		};
	}, [project.teamIds, project.visibility]);

	const resetToCommitted = () => {
		setVisibility(committedRef.current.visibility);
		setTeamIds(committedRef.current.teamIds);
	};

	const changeVisibility = async (
		nextVisibility: ResourceVisibility,
		nextTeamIds: string[],
	) => {
		if (nextVisibility === "teams" && nextTeamIds.length === 0) {
			if (visibility !== "teams") {
				setVisibility("teams");
				setTeamIds([]);
			}
			return;
		}

		const previous = committedRef.current;
		const next = {
			visibility: nextVisibility,
			teamIds: nextTeamIds,
		};
		setVisibility(nextVisibility);
		setTeamIds(nextTeamIds);
		committedRef.current = next;
		const version = ++saveVersionRef.current;
		setSaving(true);
		try {
			await updateProject(project.id, next);
		} catch (error) {
			if (version === saveVersionRef.current) {
				committedRef.current = previous;
				resetToCommitted();
				toast.error(
					getApiErrorMessage(
						error,
						"The project visibility could not be saved.",
					),
				);
			}
		} finally {
			if (version === saveVersionRef.current) setSaving(false);
		}
	};

	return (
		<div className="mt-1 flex items-center gap-1">
			<VisibilityPicker
				compact
				visibility={visibility}
				teamIds={teamIds}
				onChange={(nextVisibility, nextTeamIds) => {
					void changeVisibility(nextVisibility, nextTeamIds);
				}}
				onOpenChange={(open) => {
					if (!open && visibility === "teams" && teamIds.length === 0) {
						resetToCommitted();
					}
				}}
			/>
			{saving && (
				<Loader2
					aria-label="Saving project visibility"
					className="size-3.5 animate-spin text-meta"
				/>
			)}
		</div>
	);
}

function ProjectViewToggle({
	value,
	onChange,
}: {
	value: ProjectView;
	onChange: (value: ProjectView) => void;
}) {
	return (
		<div className="inline-flex shrink-0 rounded-[7px] border border-border bg-card p-0.5">
			{[
				{
					value: "directory" as const,
					label: "Directory view",
					icon: Folder,
				},
				{
					value: "split" as const,
					label: "Split tree view",
					icon: ListTree,
				},
			].map((option) => (
				<button
					key={option.value}
					type="button"
					title={option.label}
					aria-label={option.label}
					aria-pressed={value === option.value}
					onClick={() => {
						onChange(option.value);
					}}
					className={cn(
						"flex size-8 cursor-pointer items-center justify-center rounded-[5px] transition-colors",
						value === option.value
							? "bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal"
							: "text-meta hover:text-foreground",
					)}
				>
					<option.icon className="size-3.5" />
				</button>
			))}
		</div>
	);
}

function ResourceMenuButton({ label }: { label: string }) {
	return (
		<button
			type="button"
			aria-label={`More options for ${label}`}
			className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover hover:text-foreground data-[state=open]:bg-hover dark:hover:bg-white/10 dark:data-[state=open]:bg-white/10"
		>
			<MoreVertical className="size-4" />
		</button>
	);
}

function FolderRow({
	folder,
	onOpen,
	onCreate,
	onEdit,
	onDelete,
	canManage,
}: {
	folder: ProjectFolder;
	onOpen: () => void;
	onCreate: () => void;
	onEdit: () => void;
	onDelete: () => void;
	canManage: boolean;
}) {
	return (
		<div className="group flex min-h-14 items-center rounded-[10px] border border-border bg-card px-3 shadow-[0_1px_2px_rgba(10,25,30,0.03)] transition-[border-color,box-shadow] hover:border-border-hover hover:shadow-raised">
			<button
				type="button"
				onClick={onOpen}
				className="flex min-w-0 flex-1 cursor-pointer items-center gap-3 py-3 text-left"
			>
				<span className="flex size-9 shrink-0 items-center justify-center rounded-[9px] bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal">
					<Folder className="size-4" />
				</span>
				<span className="min-w-0">
					<span className="block truncate text-[13px] font-semibold text-foreground">
						{folder.name}
					</span>
					<span className="mt-0.5 block text-[10.5px] text-meta">
						Folder
					</span>
				</span>
			</button>
			{canManage && (
				<DropdownMenu
					trigger={<ResourceMenuButton label={folder.name} />}
					items={[
						{ label: "New folder", icon: <FolderPlus />, onClick: onCreate },
						{
							label: "Rename or move",
							icon: <FolderInput />,
							onClick: onEdit,
						},
						{
							label: "Delete folder",
							icon: <Trash2 />,
							destructive: true,
							onClick: onDelete,
						},
					]}
				/>
			)}
		</div>
	);
}

function ThreadRow({
	thread,
	onToggleCompletion,
	onMove,
}: {
	thread: ProjectThread;
	onToggleCompletion: () => void;
	onMove: () => void;
}) {
	const title = titleOf(thread);
	return (
		<div className="group flex min-h-14 items-center rounded-[10px] border border-border bg-card px-3 shadow-[0_1px_2px_rgba(10,25,30,0.03)] transition-[border-color,box-shadow] hover:border-border-hover hover:shadow-raised">
			<span className="mr-3 flex size-9 shrink-0 items-center justify-center">
				{thread.canManage ? (
					<ConversationCompletionButton
						completed={thread.completedAt !== null}
						onToggle={onToggleCompletion}
						className="size-5"
					/>
				) : (
					<span
						className={cn(
							"flex size-5 shrink-0 items-center justify-center rounded-full border",
							thread.completedAt
								? "border-emerald-600 bg-emerald-600 text-white"
								: "border-border text-transparent",
						)}
					>
						<Check className="size-3" />
					</span>
				)}
			</span>
			<Link
				href={`/agents/${thread.agentId}/chat/${thread.id}`}
				prefetch={false}
				className="min-w-0 flex-1 py-3"
			>
				<span className="block truncate text-[13px] font-semibold text-foreground">
					{title}
				</span>
				<span className="mt-0.5 block text-[10.5px] text-meta">
					{thread.completedAt ? "Completed conversation" : "Conversation"}
				</span>
			</Link>
			{thread.canManage && (
				<DropdownMenu
					trigger={<ResourceMenuButton label={title} />}
					items={[
						{
							label:
								thread.completedAt === null
									? "Mark as complete"
									: "Reopen",
							icon:
								thread.completedAt === null ? (
									<CircleCheck />
								) : (
									<Undo2 />
								),
							onClick: onToggleCompletion,
						},
						{
							label: "Move or detach conversation",
							icon: <FolderInput />,
							onClick: onMove,
						},
					]}
				/>
			)}
		</div>
	);
}

function TriggerRow({
	trigger,
	onMove,
}: {
	trigger: ProjectTrigger;
	onMove: () => void;
}) {
	return (
		<div className="group flex min-h-14 items-center rounded-[10px] border border-border bg-card px-3 shadow-[0_1px_2px_rgba(10,25,30,0.03)] transition-[border-color,box-shadow] hover:border-border-hover hover:shadow-raised">
			<span className="mr-3 flex size-9 shrink-0 items-center justify-center rounded-[9px] bg-warning-bg text-warning">
				<AlarmClock className="size-4" />
			</span>
			<Link href={`/triggers/${trigger.id}`} className="min-w-0 flex-1 py-3">
				<span className="block truncate text-[13px] font-semibold text-foreground">
					{trigger.name}
				</span>
				<span className="mt-0.5 block text-[10.5px] text-meta">
					{trigger.isActive ? "Active trigger" : "Paused trigger"}
				</span>
			</Link>
			{trigger.canManage && (
				<DropdownMenu
					trigger={<ResourceMenuButton label={trigger.name} />}
					items={[
						{
							label: "Move or detach trigger",
							icon: <FolderInput />,
							onClick: onMove,
						},
					]}
				/>
			)}
		</div>
	);
}

function ProjectTreeNavigation({
	detail,
	selectedFolderId,
	expanded,
	onSelect,
	onToggle,
}: {
	detail: ProjectDetail;
	selectedFolderId: string | null;
	expanded: Set<string>;
	onSelect: (id: string | null) => void;
	onToggle: (id: string) => void;
}) {
	const normalized = useMemo(() => normalizeProjectTree(detail), [detail]);
	const treeRef = useRef<HTMLUListElement>(null);

	const handleTreeKey = (
		event: React.KeyboardEvent<HTMLButtonElement>,
		folder: ProjectFolder | null,
		children: number,
		isOpen: boolean,
	) => {
		const nodes = Array.from(
			treeRef.current?.querySelectorAll<HTMLButtonElement>(
				"button[data-tree-id]",
			) ?? [],
		);
		const index = nodes.indexOf(event.currentTarget);
		if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
			event.preventDefault();
			const nextIndex =
				event.key === "Home"
					? 0
					: event.key === "End"
						? nodes.length - 1
						: event.key === "ArrowDown"
							? Math.min(nodes.length - 1, index + 1)
							: Math.max(0, index - 1);
			nodes[nextIndex]?.focus();
			return;
		}
		if (event.key === "ArrowLeft") {
			event.preventDefault();
			if (folder && isOpen) {
				onToggle(folder.id);
				return;
			}
			const parentId = folder?.parentId ?? null;
			nodes
				.find(
					(node) =>
						node.dataset.treeId === (parentId ?? PROJECT_ROOT),
				)
				?.focus();
			return;
		}
		if (event.key === "ArrowRight" && children > 0) {
			event.preventDefault();
			if (folder && !isOpen) {
				onToggle(folder.id);
				return;
			}
			const parentId = folder?.id ?? PROJECT_ROOT;
			nodes.find((node) => node.dataset.treeParent === parentId)?.focus();
		}
	};

	const renderFolders = (parentId: string | null, depth: number) =>
		(normalized.foldersByParent.get(parentId ?? PROJECT_ROOT) ?? []).map(
			(folder) => {
				const children =
					normalized.foldersByParent.get(folder.id)?.length ?? 0;
				const isOpen = expanded.has(folder.id);
				const isSelected = selectedFolderId === folder.id;
				return (
					<li
						key={folder.id}
						role="treeitem"
						aria-selected={isSelected}
						aria-expanded={children > 0 ? isOpen : undefined}
					>
						<div
							className={cn(
								"flex h-8 items-center rounded-[6px] transition-colors hover:bg-hover dark:hover:bg-white/10",
								isSelected && "bg-petrol-tint dark:bg-white/10",
							)}
							style={{ paddingLeft: `${depth * 12 + 4}px` }}
						>
							<button
								type="button"
								tabIndex={-1}
								aria-label={`${isOpen ? "Collapse" : "Expand"} ${folder.name}`}
								disabled={children === 0}
								onClick={() => {
									onToggle(folder.id);
								}}
								className="flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-[5px] text-meta disabled:cursor-default disabled:opacity-30"
							>
								{isOpen ? (
									<ChevronDown className="size-3.5" />
								) : (
									<ChevronRight className="size-3.5" />
								)}
							</button>
							<button
								type="button"
								data-tree-id={folder.id}
								data-tree-parent={folder.parentId ?? PROJECT_ROOT}
								tabIndex={isSelected ? 0 : -1}
								onClick={() => {
									onSelect(folder.id);
								}}
								onKeyDown={(event) => {
									if (event.key === "ArrowRight" && children > 0 && !isOpen) {
										handleTreeKey(event, folder, children, isOpen);
										return;
									}
									handleTreeKey(event, folder, children, isOpen);
								}}
								className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 self-stretch text-left"
							>
								<Folder className="size-3.5 shrink-0 text-petrol dark:text-panel-terminal" />
								<span className="truncate text-[11.5px] font-medium text-foreground">
									{folder.name}
								</span>
							</button>
						</div>
						{isOpen && children > 0 && (
							<ul role="group">{renderFolders(folder.id, depth + 1)}</ul>
						)}
					</li>
				);
			},
		);

	return (
		<ul
			ref={treeRef}
			role="tree"
			aria-label="Project folders"
			className="space-y-px"
		>
			<li role="treeitem" aria-selected={selectedFolderId === null}>
				<button
					type="button"
					data-tree-id={PROJECT_ROOT}
					data-tree-parent=""
					tabIndex={selectedFolderId === null ? 0 : -1}
					onClick={() => {
						onSelect(null);
					}}
					onKeyDown={(event) => {
						handleTreeKey(
							event,
							null,
							normalized.foldersByParent.get(PROJECT_ROOT)?.length ?? 0,
							true,
						);
					}}
					className={cn(
						"flex h-8 w-full cursor-pointer items-center gap-2 rounded-[6px] px-2 text-left transition-colors hover:bg-hover dark:hover:bg-white/10",
						selectedFolderId === null && "bg-petrol-tint dark:bg-white/10",
					)}
				>
					<Folder className="size-3.5 text-petrol dark:text-panel-terminal" />
					<span className="truncate text-[11.5px] font-semibold text-foreground">
						Project root
					</span>
				</button>
			</li>
			{renderFolders(null, 0)}
		</ul>
	);
}

export default function ProjectDetailView({
	initialDetail,
}: {
	initialDetail: ProjectDetail;
}) {
	const router = useRouter();
	const searchParams = useSearchParams();
	const confirm = useConfirmDialog();
	const workspaceId =
		useWorkspacesStore((state) => state.activeWorkspaceId) ??
		initialDetail.workspaceId;
	const cachedDetail = useProjectsStore(
		(state) => state.detailsById[initialDetail.id],
	);
	const accessLost = useProjectsStore(
		(state) => state.detailAccessLostById[initialDetail.id] ?? false,
	);
	const detail = cachedDetail ?? initialDetail;
	const setProjectDetail = useProjectsStore((state) => state.setProjectDetail);
	const mountProjectDetail = useProjectsStore(
		(state) => state.mountProjectDetail,
	);
	const unmountProjectDetail = useProjectsStore(
		(state) => state.unmountProjectDetail,
	);
	const deleteProject = useProjectsStore((state) => state.deleteProject);
	const deleteFolder = useProjectsStore((state) => state.deleteFolder);
	const refreshDetail = useProjectsStore(
		(state) => state.refreshProjectDetail,
	);
	const recentThreads = useThreadsStore((state) => state.threads);
	const setThreadCompleted = useThreadsStore(
		(state) => state.setThreadCompleted,
	);
	const allAgents = useAgentsStore((state) => state.agents);
	const agents = useMemo(
		() =>
			allAgents.filter(
				(agent) =>
					!agent.isArchived && agent.currentUserPermission != null,
			),
		[allAgents],
	);
	const normalized = useMemo(() => normalizeProjectTree(detail), [detail]);
	const requestedFolderId = searchParams.get("folder");
	const selectedFolderId =
		requestedFolderId && normalized.foldersById.has(requestedFolderId)
			? requestedFolderId
			: null;
	const requestedView = searchParams.get("view");
	const [storedView, setStoredView] = useState<ProjectView>(
		requestedView === "split" ? "split" : "directory",
	);
	const view: ProjectView =
		requestedView === "directory" || requestedView === "split"
			? requestedView
			: storedView;
	const [query, setQuery] = useState("");
	const [expanded, setExpanded] = useState<Set<string>>(new Set());
	const [infoOpen, setInfoOpen] = useState(false);
	const [folderDialog, setFolderDialog] = useState<FolderDialogState>(null);
	const [movingThread, setMovingThread] =
		useState<ThreadPlacementTarget | null>(null);
	const [movingTrigger, setMovingTrigger] =
		useState<TriggerPlacementTarget | null>(null);
	const [infoPanelWidth, setInfoPanelWidth] = useState(
		INFO_PANEL_DEFAULT_WIDTH,
	);
	const [resizingInfoPanel, setResizingInfoPanel] = useState(false);
	const infoPanelRef = useRef<HTMLElement>(null);
	const infoTriggerRef = useRef<HTMLButtonElement>(null);
	const infoResizeStart = useRef<{ x: number; width: number } | null>(null);
	const isLargeViewport = useSyncExternalStore(
		subscribeLargeViewport,
		largeViewportSnapshot,
		() => false,
	);
	const modalInfoOpen = infoOpen && !isLargeViewport;
	const updateInfoPanelWidth = (width: number) => {
		const next = clampInfoPanelWidth(width);
		setInfoPanelWidth(next);
		window.localStorage.setItem(INFO_PANEL_WIDTH_STORAGE_KEY, String(next));
	};

	useEffect(() => {
		setProjectDetail(initialDetail);
		mountProjectDetail(initialDetail.id);
		return () => {
			unmountProjectDetail(initialDetail.id);
		};
	}, [
		initialDetail,
		mountProjectDetail,
		setProjectDetail,
		unmountProjectDetail,
	]);

	useEffect(() => {
		const stored = Number.parseFloat(
			window.localStorage.getItem(INFO_PANEL_WIDTH_STORAGE_KEY) ?? "",
		);
		if (Number.isFinite(stored)) {
			queueMicrotask(() => {
				setInfoPanelWidth(clampInfoPanelWidth(stored));
			});
		}
		const reclamp = () => {
			setInfoPanelWidth((current) => clampInfoPanelWidth(current));
		};
		window.addEventListener("resize", reclamp);
		return () => {
			window.removeEventListener("resize", reclamp);
		};
	}, []);

	useEffect(() => {
		if (!modalInfoOpen) return;
		const panel = infoPanelRef.current;
		const trigger = infoTriggerRef.current;
		const focusableSelector = [
			"a[href]",
			"button:not([disabled])",
			"input:not([disabled])",
			"textarea:not([disabled])",
			"select:not([disabled])",
			'[tabindex]:not([tabindex="-1"])',
		].join(",");
		const focusable = () =>
			Array.from(
				panel?.querySelectorAll<HTMLElement>(focusableSelector) ?? [],
			).filter(
				(element) =>
					!element.hasAttribute("hidden") && element.offsetParent !== null,
			);
		const closeButton = panel?.querySelector<HTMLButtonElement>(
			'button[aria-label="Close project info"]',
		);
		closeButton?.focus();
		const handleDialogKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				event.preventDefault();
				setInfoOpen(false);
				return;
			}
			if (event.key !== "Tab") return;
			const elements = focusable();
			if (elements.length === 0) {
				event.preventDefault();
				return;
			}
			const first = elements[0];
			const last = elements.at(-1);
			const active = document.activeElement;
			if (event.shiftKey && (active === first || !panel?.contains(active))) {
				event.preventDefault();
				last?.focus();
			} else if (!event.shiftKey && (active === last || !panel?.contains(active))) {
				event.preventDefault();
				first?.focus();
			}
		};
		window.addEventListener("keydown", handleDialogKey);
		return () => {
			window.removeEventListener("keydown", handleDialogKey);
			if (
				!largeViewportSnapshot() &&
				trigger &&
				document.contains(trigger)
			) {
				trigger.focus();
			}
		};
	}, [modalInfoOpen]);

	useEffect(() => {
		if (requestedView === "directory" || requestedView === "split") {
			window.localStorage.setItem(
				viewStorageKey(workspaceId, detail.id),
				requestedView,
			);
			return;
		}
		const stored = window.localStorage.getItem(
			viewStorageKey(workspaceId, detail.id),
		);
		const next = stored === "split" ? "split" : "directory";
		const params = new URLSearchParams(searchParams.toString());
		params.set("view", next);
		queueMicrotask(() => {
			setStoredView(next);
			router.replace(`?${params.toString()}`, { scroll: false });
		});
	}, [detail.id, requestedView, router, searchParams, workspaceId]);

	const effectiveExpanded = useMemo(() => {
		const next = new Set(expanded);
		if (selectedFolderId) {
			for (const folder of getProjectFolderAncestors(
				selectedFolderId,
				normalized.foldersById,
			)) {
				next.add(folder.id);
			}
		}
		return next;
	}, [expanded, normalized.foldersById, selectedFolderId]);

	const updateQuery = (
		updates: Partial<{ folder: string | null; view: ProjectView }>,
	) => {
		const params = new URLSearchParams(searchParams.toString());
		if ("folder" in updates) {
			if (updates.folder) params.set("folder", updates.folder);
			else params.delete("folder");
		}
		if (updates.view) params.set("view", updates.view);
		router.replace(`?${params.toString()}`, { scroll: false });
	};

	const setView = (next: ProjectView) => {
		setStoredView(next);
		window.localStorage.setItem(viewStorageKey(workspaceId, detail.id), next);
		updateQuery({ view: next });
	};

	const startConversation = (folderId: string | null) => {
		const lastAgent = recentThreads[0]
			? agents.find((candidate) => candidate.id === recentThreads[0]?.agentId)
			: undefined;
		const agent = lastAgent ?? agents[0];
		if (!agent) {
			toast.error("Create or request access to an agent first.");
			return;
		}
		const params = new URLSearchParams({ projectId: detail.id });
		if (folderId) params.set("folderId", folderId);
		navigateWithUnsavedChanges(() => {
			router.push(`/agents/${agent.id}/chat?${params.toString()}`);
		});
	};

	const removeFolder = async (folder: ProjectFolder) => {
		const accepted = await confirm({
			title: `Delete ${folder.name}?`,
			description:
				"Its conversations, triggers, and child folders will move up one level.",
			confirmLabel: "Delete folder",
			destructive: true,
		});
		if (!accepted) return;
		try {
			await deleteFolder(folder.id);
			await refreshDetail(detail.id);
		} catch (error) {
			toast.error(getApiErrorMessage(error, "The folder could not be deleted."));
		}
	};

	const removeProject = async () => {
		const accepted = await confirm({
			title: `Delete ${detail.name}?`,
			description:
				"Conversations and triggers will be detached from this project. This cannot be undone.",
			confirmLabel: "Delete project",
			destructive: true,
		});
		if (!accepted) return;
		if (!prepareToDiscardUnsavedChanges()) return;
		try {
			await deleteProject(detail.id);
			router.push("/");
		} catch (error) {
			cancelPreparedNavigation();
			toast.error(getApiErrorMessage(error, "The project could not be deleted."));
		}
	};

	const toggleCompletion = async (thread: ProjectThread) => {
		try {
			await setThreadCompleted(thread.id, thread.completedAt === null);
			await refreshDetail(detail.id);
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation could not be updated."),
			);
		}
	};

	const currentKey = selectedFolderId ?? PROJECT_ROOT;
	const folders = normalized.foldersByParent.get(currentKey) ?? [];
	const threads = normalized.threadsByFolder.get(currentKey) ?? [];
	const triggers = normalized.triggersByFolder.get(currentKey) ?? [];
	const breadcrumbs = getProjectFolderAncestors(
		selectedFolderId,
		normalized.foldersById,
	);
	const folderHref = (folderId: string | null) => {
		const params = new URLSearchParams(searchParams.toString());
		if (folderId) params.set("folder", folderId);
		else params.delete("folder");
		return `/projects/${detail.id}?${params.toString()}`;
	};
	const needle = query.trim().toLocaleLowerCase();
	const searchFolders = needle
		? detail.folders.filter((folder) =>
				folder.name.toLocaleLowerCase().includes(needle),
			)
		: [];
	const searchThreads = needle
		? detail.threads.filter((thread) =>
				titleOf(thread).toLocaleLowerCase().includes(needle),
			)
		: [];
	const searchTriggers = needle
		? detail.triggers.filter((trigger) =>
				trigger.name.toLocaleLowerCase().includes(needle),
			)
		: [];

	const renderFolder = (folder: ProjectFolder) => (
		<FolderRow
			key={folder.id}
			folder={folder}
			canManage={detail.canManage}
			onOpen={() => {
				updateQuery({ folder: folder.id });
			}}
			onCreate={() => {
				setFolderDialog({ folder: null, parentId: folder.id });
			}}
			onEdit={() => {
				setFolderDialog({ folder, parentId: folder.parentId });
			}}
			onDelete={() => {
				void removeFolder(folder);
			}}
		/>
	);
	const renderThread = (thread: ProjectThread) => (
		<ThreadRow
			key={thread.id}
			thread={thread}
			onToggleCompletion={() => {
				void toggleCompletion(thread);
			}}
			onMove={() => {
				setMovingThread({
					id: thread.id,
					title: titleOf(thread),
					projectId: detail.id,
					folderId: thread.folderId,
				});
			}}
		/>
	);
	const renderTrigger = (trigger: ProjectTrigger) => (
		<TriggerRow
			key={trigger.id}
			trigger={trigger}
			onMove={() => {
				setMovingTrigger({
					id: trigger.id,
					name: trigger.name,
					projectId: detail.id,
					folderId: trigger.folderId,
				});
			}}
		/>
	);

	const resourceList = needle ? (
		searchFolders.length + searchThreads.length + searchTriggers.length > 0 ? (
			<div className="grid gap-2">
				{searchFolders.map(renderFolder)}
				{searchThreads.map(renderThread)}
				{searchTriggers.map(renderTrigger)}
			</div>
		) : (
			<div className="flex min-h-60 flex-col items-center justify-center text-center">
				<Search className="size-7 text-faint" />
				<p className="mt-3 text-[13px] font-semibold text-foreground">
					No project resources found
				</p>
				<p className="mt-1 text-[11.5px] text-meta">
					Try another folder, conversation, or trigger name.
				</p>
			</div>
		)
	) : folders.length + threads.length + triggers.length > 0 ? (
		<div className="grid gap-2">
			{folders.map(renderFolder)}
			{threads.map(renderThread)}
			{triggers.map(renderTrigger)}
		</div>
	) : (
		<div className="flex min-h-60 flex-col items-center justify-center rounded-[12px] border border-dashed border-border bg-sidebar/30 text-center">
			<Folder className="size-8 text-faint" />
			<p className="mt-3 text-[13px] font-semibold text-foreground">
				This folder is empty
			</p>
			<p className="mt-1 max-w-xs text-[11.5px] leading-5 text-meta">
				Start a conversation or create a folder to organize project work.
			</p>
		</div>
	);

	return (
		<>
			{accessLost && (
				<div className="fixed inset-0 z-[70] flex items-center justify-center bg-background px-6">
					<div className="max-w-sm text-center">
						<span className="mx-auto flex size-12 items-center justify-center rounded-[12px] bg-sidebar text-meta">
							<Folder className="size-5" />
						</span>
						<h1 className="mt-4 font-display text-[20px] font-bold text-foreground">
							Project access changed
						</h1>
						<p className="mt-2 text-[12.5px] leading-5 text-meta">
							This project was removed or is no longer available in the
							current workspace.
						</p>
						<Link
							href="/"
							className="mt-5 inline-flex items-center whitespace-nowrap rounded-[7px] bg-petrol px-4 py-2 text-[12.5px] font-semibold text-white"
						>
							Return to workspace
						</Link>
					</div>
				</div>
			)}
			<div
				aria-hidden={accessLost}
				inert={accessLost}
				className={cn(
					"flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300",
					accessLost && "invisible",
					resizingInfoPanel && "select-none",
				)}
			>
			<div className="contents" inert={modalInfoOpen}>
			<SubpageHeader
				trail={[
					{ label: "workspace", href: "/" },
					{ label: "projects" },
					{
						label: detail.emoji
							? `${detail.emoji} ${detail.name}`
							: detail.name,
						href: selectedFolderId ? folderHref(null) : undefined,
					},
					...breadcrumbs.map((folder) => ({
						label: folder.name,
						href:
							folder.id === selectedFolderId
								? undefined
								: folderHref(folder.id),
					})),
				]}
			>
				<HeaderButton
					ref={infoTriggerRef}
					className="lg:hidden"
					aria-haspopup="dialog"
					aria-expanded={modalInfoOpen}
					aria-controls="project-info-dialog"
					onClick={() => {
						setInfoOpen(true);
					}}
				>
					<PanelRight className="size-3.5" />
					Info
				</HeaderButton>
				{detail.canManage ? (
					<DropdownMenu
						items={[
							{
								label: "Delete project",
								icon: <Trash2 />,
								destructive: true,
								onClick: () => {
									void removeProject();
								},
							},
						]}
					/>
				) : (
					<HeaderReadOnly title="You can view this project but cannot change it." />
				)}
			</SubpageHeader>
			</div>

			<div className="flex min-h-0 flex-1 overflow-hidden">
				<div
					inert={modalInfoOpen}
					className="flex min-w-0 flex-1 flex-col"
				>
					<div className="border-b border-border px-4 py-3 sm:px-6">
						<div className="flex items-center gap-2">
							<div className="relative min-w-0 flex-1">
								<Search className="absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-meta" />
								<input
									value={query}
									onChange={(event) => {
										setQuery(event.target.value);
									}}
									placeholder="Search folders, conversations, and triggers"
									className="h-9 w-full rounded-[8px] border border-input bg-card pl-9 pr-3 text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]"
								/>
							</div>
							<ProjectViewToggle value={view} onChange={setView} />
							<DropdownMenu
								trigger={
									<button
										type="button"
										aria-label="Create project resource"
										className="flex h-9 shrink-0 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] bg-petrol px-3 text-[12px] font-semibold text-white transition-opacity hover:opacity-90"
									>
										<SquarePen className="size-3.5" />
										<span className="hidden sm:inline">New</span>
									</button>
								}
								items={[
									{
										label: "New conversation",
										icon: <SquarePen />,
										onClick: () => {
											startConversation(selectedFolderId);
										},
									},
									...(detail.canManage
										? [
												{
													label: "New folder",
													icon: <FolderPlus />,
													onClick: () => {
														setFolderDialog({
															folder: null,
															parentId: selectedFolderId,
														});
													},
												},
											]
										: []),
								]}
							/>
						</div>
					</div>

					<div className="flex min-h-0 flex-1">
						{view === "split" && (
							<aside className="hidden w-56 shrink-0 overflow-y-auto border-r border-border bg-sidebar/30 p-3 sm:block">
								<ProjectTreeNavigation
									detail={detail}
									selectedFolderId={selectedFolderId}
									expanded={effectiveExpanded}
									onSelect={(id) => {
										updateQuery({ folder: id });
									}}
									onToggle={(id) => {
										setExpanded((current) => {
											const next = new Set(current);
											if (next.has(id)) next.delete(id);
											else next.add(id);
											return next;
										});
									}}
								/>
							</aside>
						)}
						<main className="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
							<div className="mb-4 flex w-full items-end justify-between gap-3">
								<div className="min-w-0 flex-1">
									{selectedFolderId === null ? (
										<ProjectIdentityHeading project={detail} />
									) : (
										<h1 className="truncate font-display text-[20px] font-bold text-foreground">
											{normalized.foldersById.get(selectedFolderId)?.name}
										</h1>
									)}
									<p className="mt-1 text-[11px] text-meta">
										{needle
											? `${searchFolders.length + searchThreads.length + searchTriggers.length} search results`
											: `${folders.length} folders / ${threads.length} conversations / ${triggers.length} triggers`}
									</p>
									{selectedFolderId === null && (
										<>
											<ProjectDescription project={detail} />
											{detail.canManage && (
												<ProjectVisibilityEditor project={detail} />
											)}
										</>
									)}
								</div>
							</div>
							<div
								className={cn(
									"w-full",
									view === "split" && "mx-auto max-w-3xl",
								)}
							>
								{view === "split" && (
									<div className="mb-4 sm:hidden">
										<label className="text-[11px] font-semibold text-label">
											Folder
											<select
												value={selectedFolderId ?? ""}
												onChange={(event) => {
													updateQuery({ folder: event.target.value || null });
												}}
												className="mt-1.5 h-9 w-full rounded-[8px] border border-input bg-card px-3 text-[12px] text-foreground outline-none focus:border-petrol"
											>
												<option value="">Project root</option>
												{detail.folders.map((folder) => (
													<option key={folder.id} value={folder.id}>
														{getProjectFolderAncestors(
															folder.id,
															normalized.foldersById,
														)
															.map((item) => item.name)
															.join(" / ")}
													</option>
												))}
											</select>
										</label>
									</div>
								)}
								{resourceList}
							</div>
						</main>
					</div>
				</div>

				<button
					type="button"
					aria-label="Close project info"
					tabIndex={modalInfoOpen ? 0 : -1}
					onClick={() => {
						setInfoOpen(false);
					}}
					className={cn(
						"fixed inset-0 z-40 bg-black/35 transition-opacity lg:hidden",
						modalInfoOpen
							? "opacity-100"
							: "pointer-events-none opacity-0",
					)}
				/>
				<aside
					ref={infoPanelRef}
					id="project-info-dialog"
					role={isLargeViewport ? undefined : "dialog"}
					aria-modal={isLargeViewport ? undefined : true}
					aria-label="Project info"
					aria-hidden={!isLargeViewport && !modalInfoOpen}
					inert={!isLargeViewport && !modalInfoOpen}
					style={isLargeViewport ? { width: infoPanelWidth } : undefined}
					className={cn(
						"fixed inset-y-0 right-0 z-50 flex w-[min(92vw,600px)] shrink-0 flex-col border-l border-border bg-background shadow-2xl transition-transform duration-200 lg:relative lg:inset-auto lg:z-auto lg:min-w-[340px] lg:max-w-[45vw] lg:translate-x-0 lg:shadow-none",
						modalInfoOpen ? "translate-x-0" : "translate-x-full",
					)}
				>
					<div
						role="separator"
						aria-label="Resize project info panel"
						aria-orientation="vertical"
						aria-valuemin={INFO_PANEL_MIN_WIDTH}
						aria-valuemax={
							isLargeViewport
								? Math.round(window.innerWidth * 0.45)
								: INFO_PANEL_DEFAULT_WIDTH
						}
						aria-valuenow={Math.round(infoPanelWidth)}
						tabIndex={0}
						onPointerDown={(event) => {
							if (event.button !== 0) return;
							event.currentTarget.setPointerCapture(event.pointerId);
							infoResizeStart.current = {
								x: event.clientX,
								width: infoPanelWidth,
							};
							setResizingInfoPanel(true);
						}}
						onPointerMove={(event) => {
							if (!infoResizeStart.current) return;
							updateInfoPanelWidth(
								infoResizeStart.current.width +
									infoResizeStart.current.x -
									event.clientX,
							);
						}}
						onPointerUp={(event) => {
							if (event.currentTarget.hasPointerCapture(event.pointerId)) {
								event.currentTarget.releasePointerCapture(event.pointerId);
							}
							infoResizeStart.current = null;
							setResizingInfoPanel(false);
						}}
						onPointerCancel={() => {
							infoResizeStart.current = null;
							setResizingInfoPanel(false);
						}}
						onLostPointerCapture={() => {
							infoResizeStart.current = null;
							setResizingInfoPanel(false);
						}}
						onKeyDown={(event) => {
							if (
								event.key !== "ArrowLeft" &&
								event.key !== "ArrowRight"
							) {
								return;
							}
							event.preventDefault();
							updateInfoPanelWidth(
								infoPanelWidth + (event.key === "ArrowLeft" ? 8 : -8),
							);
						}}
						className={cn(
							"group absolute inset-y-0 left-[-4px] z-10 hidden w-2 cursor-col-resize touch-none outline-none lg:block",
							"after:absolute after:inset-y-0 after:left-1/2 after:w-px after:-translate-x-1/2 after:bg-transparent after:transition-colors hover:after:bg-petrol/45 focus-visible:after:bg-petrol",
							resizingInfoPanel && "after:bg-petrol",
						)}
					/>
					<div className="flex h-[52px] shrink-0 items-center gap-2 border-b border-border px-4 lg:hidden">
						<Info className="size-4 text-petrol" />
						<div className="min-w-0">
							<p className="text-[13px] font-semibold text-foreground">
								Project info
							</p>
							<p className="truncate text-[10.5px] text-meta">
								Instructions, context files, and skills
							</p>
						</div>
						<button
							type="button"
							aria-label="Close project info"
							onClick={() => {
								setInfoOpen(false);
							}}
							className="ml-auto flex size-8 cursor-pointer items-center justify-center rounded-[7px] text-meta hover:bg-hover hover:text-foreground dark:hover:bg-white/10"
						>
							<X className="size-4" />
						</button>
					</div>
					<div className="min-h-0 flex-1">
						<ProjectInfoPanel detail={detail} />
					</div>
				</aside>
			</div>
			<FolderDialog
				open={folderDialog !== null}
				onOpenChange={(open) => {
					if (!open) setFolderDialog(null);
				}}
				project={detail}
				folder={folderDialog?.folder ?? null}
				initialParentId={folderDialog?.parentId ?? null}
			/>
			<ThreadPlacementDialog
				open={movingThread !== null}
				onOpenChange={(open) => {
					if (!open) {
						setMovingThread(null);
						void refreshDetail(detail.id);
					}
				}}
				thread={movingThread}
			/>
			<TriggerPlacementDialog
				open={movingTrigger !== null}
				onOpenChange={(open) => {
					if (!open) {
						setMovingTrigger(null);
						void refreshDetail(detail.id);
					}
				}}
				trigger={movingTrigger}
			/>
			</div>
		</>
	);
}

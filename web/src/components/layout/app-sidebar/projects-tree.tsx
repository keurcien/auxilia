"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
	AlarmClock,
	Building2,
	Check,
	CircleCheck,
	ChevronDown,
	ChevronRight,
	Folder,
	FolderInput,
	FolderPlus,
	LockKeyhole,
	MoreVertical,
	Pencil,
	Plus,
	SquarePen,
	Trash2,
	Undo2,
	Users,
} from "lucide-react";
import { toast } from "sonner";

import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { getApiErrorMessage } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { navigateWithUnsavedChanges } from "@/hooks/use-unsaved-changes-warning";
import { useAgentsStore } from "@/stores/agents-store";
import { useProjectsStore } from "@/stores/projects-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useWorkspacesStore } from "@/stores/workspaces-store";
import type {
	Project,
	ProjectFolder,
	ProjectThread,
	ProjectTree,
} from "@/types/projects";
import { ConversationCompletionButton } from "./conversation-completion-button";
import { FolderDialog } from "./folder-dialog";
import { ProjectDialog } from "./project-dialog";
import {
	ThreadPlacementDialog,
	type ThreadPlacementTarget,
} from "./thread-placement-dialog";
import {
	TriggerPlacementDialog,
	type TriggerPlacementTarget,
} from "./trigger-placement-dialog";

const expandedStorageKey = (workspaceId: string) =>
	`auxilia:projects-expanded:${workspaceId}`;

type FolderDialogState = {
	project: ProjectTree;
	folder: ProjectFolder | null;
	parentId: string | null;
} | null;

function ProjectVisibilityIcon({
	visibility,
}: {
	visibility: Project["visibility"];
}) {
	const Icon =
		visibility === "personal"
			? LockKeyhole
			: visibility === "teams"
				? Users
				: Building2;
	const label =
		visibility === "personal"
			? "Personal"
			: visibility === "teams"
				? "Teams"
				: "Workspace";
	return (
		<span
			aria-label={`${label} visibility`}
			title={`${label} visibility`}
			className="pointer-events-none absolute right-1 flex size-6 items-center justify-center text-sidebar-muted transition-opacity group-hover/project:opacity-0 group-focus-within/project:opacity-0"
		>
			<Icon className="size-3.5" />
		</span>
	);
}

export function ProjectsTree({
	pathname,
	closeMobile,
}: {
	pathname: string;
	closeMobile: () => void;
}) {
	const router = useRouter();
	const confirm = useConfirmDialog();
	const workspaceId =
		useWorkspacesStore((state) => state.activeWorkspaceId) ?? "unknown";
	const projects = useProjectsStore((state) => state.tree);
	const isLoading = useProjectsStore((state) => state.isLoading);
	const deleteProject = useProjectsStore((state) => state.deleteProject);
	const deleteFolder = useProjectsStore((state) => state.deleteFolder);
	const refreshTree = useProjectsStore((state) => state.refreshTree);
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
	const [expanded, setExpanded] = useState<Set<string>>(new Set());
	const [projectDialogOpen, setProjectDialogOpen] = useState(false);
	const [editingProject, setEditingProject] = useState<Project | null>(null);
	const [folderDialog, setFolderDialog] = useState<FolderDialogState>(null);
	const [movingThread, setMovingThread] =
		useState<ThreadPlacementTarget | null>(null);
	const [movingTrigger, setMovingTrigger] =
		useState<TriggerPlacementTarget | null>(null);
	const activeProjectId = pathname.match(/^\/projects\/([^/]+)/)?.[1] ?? null;

	useEffect(() => {
		let cancelled = false;
		try {
			const value = JSON.parse(
				window.localStorage.getItem(expandedStorageKey(workspaceId)) ?? "[]",
			) as unknown;
			const next = new Set(
				Array.isArray(value)
					? value.filter((item): item is string => typeof item === "string")
					: [],
			);
			if (activeProjectId) next.add(activeProjectId);
			queueMicrotask(() => {
				if (!cancelled) setExpanded(next);
			});
		} catch {
			queueMicrotask(() => {
				if (!cancelled) setExpanded(new Set());
			});
		}
		return () => {
			cancelled = true;
		};
	}, [activeProjectId, workspaceId]);

	const toggleExpanded = (id: string) => {
		setExpanded((current) => {
			const next = new Set(current);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			window.localStorage.setItem(
				expandedStorageKey(workspaceId),
				JSON.stringify([...next]),
			);
			return next;
		});
	};

	const startConversation = (projectId: string, folderId: string | null) => {
		const lastAgent = recentThreads[0]
			? agents.find((candidate) => candidate.id === recentThreads[0]?.agentId)
			: undefined;
		const agent = lastAgent ?? agents[0];
		if (!agent) return;
		const query = new URLSearchParams({ projectId });
		if (folderId) query.set("folderId", folderId);
		const navigated = navigateWithUnsavedChanges(() => {
			router.push(`/agents/${agent.id}/chat?${query.toString()}`);
		});
		if (navigated) closeMobile();
	};

	const removeProject = async (project: ProjectTree) => {
		const accepted = await confirm({
			title: `Delete ${project.name}?`,
			description:
				"Conversations and triggers will be detached from this project. This cannot be undone.",
			confirmLabel: "Delete project",
			destructive: true,
		});
		if (!accepted) return;
		try {
			await deleteProject(project.id);
		} catch (error) {
			toast.error(getApiErrorMessage(error, "The project could not be deleted."));
		}
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
		} catch (error) {
			toast.error(getApiErrorMessage(error, "The folder could not be deleted."));
		}
	};

	const toggleCompletion = async (thread: ProjectThread) => {
		try {
			await setThreadCompleted(thread.id, thread.completedAt === null);
			await refreshTree();
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation could not be updated."),
			);
		}
	};

	if (projects.length === 0 && !isLoading) {
		return (
			<div className="px-2 py-8 text-center group-data-[collapsible=icon]:hidden">
				<Folder className="mx-auto size-5 text-sidebar-muted-highlight" />
				<p className="mt-2 text-[12px] font-medium text-sidebar-muted">
					No projects yet
				</p>
				<button
					type="button"
					onClick={() => {
						setEditingProject(null);
						setProjectDialogOpen(true);
					}}
					className="mt-3 inline-flex cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-[7px] border border-input bg-card px-2.5 py-1.5 text-[11.5px] font-semibold text-sidebar-foreground"
				>
					<Plus className="size-3.5" />
					Create project
				</button>
				<ProjectDialog
					open={projectDialogOpen}
					onOpenChange={setProjectDialogOpen}
					project={editingProject}
				/>
			</div>
		);
	}

	return (
		<>
			<ul className="flex flex-col gap-px">
				<li className="mb-1">
					<button
						type="button"
						onClick={() => {
							setEditingProject(null);
							setProjectDialogOpen(true);
						}}
						className="flex h-8 w-full cursor-pointer items-center gap-2 whitespace-nowrap rounded-[7px] px-2 text-[11.5px] font-semibold text-sidebar-muted transition-colors hover:bg-sidebar-hover hover:text-sidebar-foreground"
					>
						<Plus className="size-3.5" />
						New project
					</button>
				</li>
				{projects.map((project) => {
					const isOpen = expanded.has(project.id);
					const isActive = activeProjectId === project.id;
					const count = project.threads.length + project.triggers.length;
					return (
						<li key={project.id} className="group/project">
							<div
								className={cn(
									"relative flex h-9 items-center rounded-[7px] hover:bg-sidebar-hover",
									isActive && "bg-sidebar-accent",
								)}
							>
								<button
									type="button"
									aria-label={`${isOpen ? "Collapse" : "Expand"} ${project.name}`}
									aria-expanded={isOpen}
									onClick={() => {
										toggleExpanded(project.id);
									}}
									className="ml-1 flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[6px] text-sidebar-muted hover:bg-sidebar-hover"
								>
									{isOpen ? (
										<ChevronDown className="size-3.5 shrink-0 text-sidebar-muted" />
									) : (
										<ChevronRight className="size-3.5 shrink-0 text-sidebar-muted" />
									)}
								</button>
								<Link
									href={`/projects/${project.id}`}
									onClick={closeMobile}
									className="flex min-w-0 flex-1 items-center gap-2 self-stretch pr-9 text-left"
								>
									{project.emoji ? (
										<span
											aria-hidden
											className="flex size-4 shrink-0 items-center justify-center text-[14px]"
										>
											{project.emoji}
										</span>
									) : (
										<Folder className="size-4 shrink-0 text-sidebar-active-icon" />
									)}
									<span
										className={cn(
											"truncate text-[12.5px] text-sidebar-foreground",
											isActive ? "font-semibold" : "font-medium",
										)}
									>
										{project.name}
									</span>
									<span className="ml-auto font-mono text-[10px] text-sidebar-section-label">
										{count}
									</span>
								</Link>
								<ProjectVisibilityIcon visibility={project.visibility} />
								<DropdownMenu
									side="right"
									align="start"
									trigger={
										<button
											type="button"
											aria-label={`More options for ${project.name}`}
											className="absolute right-1 z-10 flex size-6 cursor-pointer items-center justify-center rounded-md text-sidebar-muted opacity-0 hover:bg-sidebar-accent group-hover/project:opacity-100 focus-visible:opacity-100 data-[state=open]:bg-sidebar-accent data-[state=open]:opacity-100"
										>
											<MoreVertical className="size-3.5" />
										</button>
									}
									items={[
										{
											label: "New conversation",
											icon: <SquarePen />,
											onClick: () => {
												startConversation(project.id, null);
											},
										},
										...(project.canManage
											? [
													{
														label: "New folder",
														icon: <FolderPlus />,
														onClick: () => {
															setFolderDialog({
																project,
																folder: null,
																parentId: null,
															});
														},
													},
													{
														label: "Edit project",
														icon: <Pencil />,
														onClick: () => {
															setEditingProject(project);
															setProjectDialogOpen(true);
														},
													},
													{
														label: "Delete project",
														icon: <Trash2 />,
														destructive: true,
														onClick: () => {
															void removeProject(project);
														},
													},
												]
											: []),
									]}
								/>
							</div>
							{isOpen && (
								<div className="ml-[15px] border-l border-sidebar-border pl-1.5">
									<ProjectResources
										project={project}
										folderId={null}
										depth={0}
										expanded={expanded}
										pathname={pathname}
										onToggleExpanded={toggleExpanded}
										onStartConversation={startConversation}
										onEditFolder={(folder) => {
											setFolderDialog({ project, folder, parentId: null });
										}}
										onCreateFolder={(parentId) => {
											setFolderDialog({
												project,
												folder: null,
												parentId,
											});
										}}
										onDeleteFolder={(folder) => {
											void removeFolder(folder);
										}}
										onMoveThread={setMovingThread}
										onMoveTrigger={setMovingTrigger}
										onToggleCompletion={(thread) => {
											void toggleCompletion(thread);
										}}
										closeMobile={closeMobile}
									/>
								</div>
							)}
						</li>
					);
				})}
			</ul>
			<ProjectDialog
				open={projectDialogOpen}
				onOpenChange={setProjectDialogOpen}
				project={editingProject}
			/>
			<FolderDialog
				open={folderDialog !== null}
				onOpenChange={(open) => {
					if (!open) setFolderDialog(null);
				}}
				project={folderDialog?.project ?? null}
				folder={folderDialog?.folder ?? null}
				initialParentId={folderDialog?.parentId ?? null}
			/>
			<ThreadPlacementDialog
				open={movingThread !== null}
				onOpenChange={(open) => {
					if (!open) setMovingThread(null);
				}}
				thread={movingThread}
			/>
			<TriggerPlacementDialog
				open={movingTrigger !== null}
				onOpenChange={(open) => {
					if (!open) setMovingTrigger(null);
				}}
				trigger={movingTrigger}
			/>
		</>
	);
}

function ProjectResources({
	project,
	folderId,
	depth,
	expanded,
	pathname,
	onToggleExpanded,
	onStartConversation,
	onEditFolder,
	onCreateFolder,
	onDeleteFolder,
	onMoveThread,
	onMoveTrigger,
	onToggleCompletion,
	closeMobile,
}: {
	project: ProjectTree;
	folderId: string | null;
	depth: number;
	expanded: Set<string>;
	pathname: string;
	onToggleExpanded: (id: string) => void;
	onStartConversation: (projectId: string, folderId: string | null) => void;
	onEditFolder: (folder: ProjectFolder) => void;
	onCreateFolder: (parentId: string) => void;
	onDeleteFolder: (folder: ProjectFolder) => void;
	onMoveThread: (thread: ThreadPlacementTarget) => void;
	onMoveTrigger: (trigger: TriggerPlacementTarget) => void;
	onToggleCompletion: (thread: ProjectThread) => void;
	closeMobile: () => void;
}) {
	const folders = useMemo(
		() => project.folders.filter((folder) => folder.parentId === folderId),
		[folderId, project.folders],
	);
	const threads = project.threads.filter((thread) => thread.folderId === folderId);
	const triggers = project.triggers.filter((trigger) => trigger.folderId === folderId);

	return (
		<ul className="flex flex-col gap-px">
			{folders.map((folder) => {
				const isOpen = expanded.has(folder.id);
				return (
					<li key={folder.id} className="group/folder">
						<div className="relative flex h-8 items-center rounded-[6px] hover:bg-sidebar-hover">
							<button
								type="button"
								onClick={() => {
									onToggleExpanded(folder.id);
								}}
								className="flex min-w-0 flex-1 cursor-pointer items-center gap-1.5 px-1.5 text-left"
							>
								{isOpen ? (
									<ChevronDown className="size-3 shrink-0 text-sidebar-muted" />
								) : (
									<ChevronRight className="size-3 shrink-0 text-sidebar-muted" />
								)}
								<Folder className="size-3.5 shrink-0 text-sidebar-muted-highlight" />
								<span className="truncate text-[12px] font-medium text-sidebar-foreground">
									{folder.name}
								</span>
							</button>
							<DropdownMenu
									side="right"
									align="start"
									trigger={
										<button
											type="button"
											aria-label={`More options for ${folder.name}`}
											className="absolute right-1 flex size-6 cursor-pointer items-center justify-center rounded-md text-sidebar-muted opacity-0 hover:bg-sidebar-accent group-hover/folder:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
										>
											<MoreVertical className="size-3.5" />
										</button>
									}
									items={[
										{
											label: "New conversation",
											icon: <SquarePen />,
											onClick: () => {
												onStartConversation(project.id, folder.id);
											},
										},
										...(project.canManage
											? [
													{
														label: "New folder",
														icon: <FolderPlus />,
														onClick: () => {
															onCreateFolder(folder.id);
														},
													},
													{
														label: "Rename or move",
														icon: <FolderInput />,
														onClick: () => {
															onEditFolder(folder);
														},
													},
													{
														label: "Delete folder",
														icon: <Trash2 />,
														destructive: true,
														onClick: () => {
															onDeleteFolder(folder);
														},
													},
												]
											: []),
									]}
								/>
						</div>
						{isOpen && (
							<div className="ml-[10px] border-l border-sidebar-border pl-1.5">
								<ProjectResources
									project={project}
									folderId={folder.id}
									depth={depth + 1}
									expanded={expanded}
									pathname={pathname}
									onToggleExpanded={onToggleExpanded}
									onStartConversation={onStartConversation}
									onEditFolder={onEditFolder}
									onCreateFolder={onCreateFolder}
									onDeleteFolder={onDeleteFolder}
									onMoveThread={onMoveThread}
									onMoveTrigger={onMoveTrigger}
									onToggleCompletion={onToggleCompletion}
									closeMobile={closeMobile}
								/>
							</div>
						)}
					</li>
				);
			})}
			{threads.map((thread) => {
				const owned = thread.canManage;
				const title = thread.title?.trim() || "Untitled conversation";
				const active = pathname === `/agents/${thread.agentId}/chat/${thread.id}`;
				return (
					<li key={thread.id} className="group/resource relative">
						<Link
							href={`/agents/${thread.agentId}/chat/${thread.id}`}
							prefetch={false}
							onClick={closeMobile}
							className={cn(
								"flex h-8 items-center gap-2 rounded-[6px] px-1.5 pr-7 text-[11.5px] hover:bg-sidebar-hover",
								active && "bg-sidebar-accent font-semibold",
							)}
						>
							{owned ? (
								<ConversationCompletionButton
									completed={thread.completedAt !== null}
									onToggle={() => {
										onToggleCompletion(thread);
									}}
									className="size-4"
								/>
							) : (
								<span
									className={cn(
										"flex size-4 shrink-0 items-center justify-center rounded-full border",
										thread.completedAt
											? "border-emerald-600 bg-emerald-600 text-white"
											: "border-sidebar-muted-highlight text-transparent",
									)}
								>
									<Check className="size-2.5" strokeWidth={3} />
								</span>
							)}
							<span className="truncate text-sidebar-foreground">{title}</span>
						</Link>
						{owned && (
							<DropdownMenu
								side="right"
								align="start"
								trigger={
									<button
										type="button"
										aria-label={`More options for ${title}`}
										className="absolute right-1 top-1 flex size-6 cursor-pointer items-center justify-center rounded-md text-sidebar-muted opacity-0 hover:bg-sidebar-accent group-hover/resource:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
									>
										<MoreVertical className="size-3.5" />
									</button>
								}
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
										onClick: () => {
											onToggleCompletion(thread);
										},
									},
									{
										label: "Move conversation",
										icon: <FolderInput />,
										onClick: () => {
											onMoveThread({
												id: thread.id,
												title,
												projectId: project.id,
												folderId: thread.folderId,
											});
										},
									},
								]}
							/>
						)}
					</li>
				);
			})}
			{triggers.map((trigger) => (
				<li key={trigger.id} className="group/resource relative">
					<Link
						href={`/triggers/${trigger.id}`}
						onClick={closeMobile}
						className="flex h-8 items-center gap-2 rounded-[6px] px-1.5 pr-7 text-[11.5px] text-sidebar-foreground hover:bg-sidebar-hover"
					>
						<AlarmClock className="size-3.5 shrink-0 text-sidebar-muted-highlight" />
						<span className="truncate">{trigger.name}</span>
					</Link>
					{trigger.canManage && (
						<DropdownMenu
							side="right"
							align="start"
							trigger={
								<button
									type="button"
									aria-label={`More options for ${trigger.name}`}
									className="absolute right-1 top-1 flex size-6 cursor-pointer items-center justify-center rounded-md text-sidebar-muted opacity-0 hover:bg-sidebar-accent group-hover/resource:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
								>
									<MoreVertical className="size-3.5" />
								</button>
							}
							items={[
								{
									label: "Move trigger",
									icon: <FolderInput />,
									onClick: () => {
										onMoveTrigger({
											id: trigger.id,
											name: trigger.name,
											projectId: project.id,
											folderId: trigger.folderId,
										});
									},
								},
							]}
						/>
					)}
				</li>
			))}
		</ul>
	);
}

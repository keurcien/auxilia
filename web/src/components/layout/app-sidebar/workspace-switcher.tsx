"use client";

import { useMemo, useRef, useState } from "react";
import * as DropdownMenuPrimitive from "@radix-ui/react-dropdown-menu";
import { AlertCircle, Check, ChevronsUpDown, Loader2, Pencil, Plus, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";

import { CreateWorkspaceDialog } from "@/components/layout/app-sidebar/create-workspace-dialog";
import { EditWorkspaceDialog } from "@/components/layout/app-sidebar/edit-workspace-dialog";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { WorkspaceAvatar } from "@/components/ui/workspace-avatar";
import { currentWorkspaceSwitchDestination } from "@/lib/workspace-navigation";
import { useUserStore } from "@/stores/user-store";
import { useWorkspacesStore } from "@/stores/workspaces-store";

export function WorkspaceSwitcher() {
	const user = useUserStore((state) => state.user);
	const workspaces = useWorkspacesStore((state) => state.workspaces);
	const activeWorkspaceId = useWorkspacesStore((state) => state.activeWorkspaceId);
	const isInitialized = useWorkspacesStore((state) => state.isInitialized);
	const isLoading = useWorkspacesStore((state) => state.isLoading);
	const isSwitching = useWorkspacesStore((state) => state.isSwitching);
	const error = useWorkspacesStore((state) => state.error);
	const hydrate = useWorkspacesStore((state) => state.hydrate);
	const selectWorkspace = useWorkspacesStore((state) => state.selectWorkspace);
	const [open, setOpen] = useState(false);
	const [createOpen, setCreateOpen] = useState(false);
	const [editWorkspaceId, setEditWorkspaceId] = useState<string | null>(null);
	const [editOpen, setEditOpen] = useState(false);
	const [query, setQuery] = useState("");
	const inputRef = useRef<HTMLInputElement>(null);
	const active = workspaces.find((workspace) => workspace.id === activeWorkspaceId);
	const editWorkspace =
		workspaces.find((workspace) => workspace.id === editWorkspaceId) ?? null;
	const filtered = useMemo(() => {
		const needle = query.trim().toLowerCase();
		return needle
			? workspaces.filter((workspace) => workspace.name.toLowerCase().includes(needle))
			: workspaces;
	}, [query, workspaces]);

	const handleOpenChange = (next: boolean) => {
		setOpen(next);
		if (next) requestAnimationFrame(() => { inputRef.current?.focus(); });
		else setQuery("");
	};

	const choose = async (workspaceId: string) => {
		if (workspaceId === activeWorkspaceId) return;
		const destination = currentWorkspaceSwitchDestination();
		try {
			await selectWorkspace(workspaceId);
			window.location.assign(destination);
		} catch {
			toast.error("Could not switch workspace. Please try again.");
		}
	};

	const edit = (workspaceId: string) => {
		setEditWorkspaceId(workspaceId);
		setOpen(false);
		window.setTimeout(() => {
			setEditOpen(true);
		}, 0);
	};

	return (
		<>
			<DropdownMenuPrimitive.Root open={open} onOpenChange={handleOpenChange}>
				<DropdownMenuPrimitive.Trigger asChild>
					<button
						type="button"
						aria-label={`Workspace: ${active?.name ?? "Loading"}`}
						disabled={isSwitching}
						className="flex h-10 w-full cursor-pointer items-center gap-2 rounded-[8px] border border-sidebar-border bg-sidebar-accent/60 px-2 text-left outline-none transition-colors hover:bg-sidebar-hover focus-visible:ring-2 focus-visible:ring-sidebar-ring disabled:cursor-wait group-data-[collapsible=icon]:size-[38px] group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:p-0"
					>
						<WorkspaceAvatar
							workspaceId={active?.id}
							name={active?.name}
							emoji={active?.emoji}
							color={active?.color}
							imageRevision={active?.imageRevision}
							size="xs"
							className="bg-petrol text-white"
						/>
						<span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-sidebar-foreground group-data-[collapsible=icon]:hidden">
							{active?.name ?? (error ? "Workspace unavailable" : isInitialized ? "Workspace" : "Loading…")}
						</span>
						{isSwitching || isLoading ? (
							<Loader2 className="size-3.5 animate-spin text-sidebar-muted group-data-[collapsible=icon]:hidden" />
						) : error ? (
							<AlertCircle className="size-3.5 text-destructive group-data-[collapsible=icon]:hidden" />
						) : (
							<ChevronsUpDown className="size-3.5 text-sidebar-muted group-data-[collapsible=icon]:hidden" />
						)}
					</button>
				</DropdownMenuPrimitive.Trigger>
				<DropdownMenuPrimitive.Portal>
					<DropdownMenuPrimitive.Content
						align="start"
						sideOffset={7}
						className="z-50 w-[280px] overflow-hidden rounded-[11px] border border-hairline bg-canvas shadow-[0_18px_48px_-18px_rgba(10,25,30,0.32)] data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:slide-in-from-top-1 dark:border-white/10 dark:bg-card"
					>
						<div className="p-2">
							<div className="flex h-9 items-center gap-2 rounded-[7px] bg-sidebar px-2.5 dark:bg-white/5">
								<Search className="size-3.5 text-faint" />
								<input
									ref={inputRef}
									value={query}
									onChange={(event) => { setQuery(event.target.value); }}
									onKeyDown={(event) => { if (event.key.length === 1) event.stopPropagation(); }}
									placeholder="Search workspaces…"
									aria-label="Search workspaces"
									className="min-w-0 flex-1 bg-transparent text-[12.5px] text-foreground outline-none placeholder:text-faint"
								/>
							</div>
						</div>
						{error && (
							<DropdownMenuPrimitive.Item
								disabled={isLoading}
								onSelect={() => { void hydrate(); }}
								className="mx-1 flex cursor-pointer select-none items-center gap-2 rounded-[7px] px-2.5 py-2 text-[12.5px] font-semibold text-destructive outline-none focus:bg-hover disabled:opacity-50 dark:focus:bg-white/5"
							>
								<RefreshCw className="size-3.5" />
								Retry loading workspaces
							</DropdownMenuPrimitive.Item>
						)}
						{(user?.isInstanceOwner ||
							user?.canCreateWorkspace ||
							((isInitialized || error) && workspaces.length === 0)) && (
							<DropdownMenuPrimitive.Item
								onSelect={() => { setCreateOpen(true); }}
								className="mx-1 flex cursor-pointer select-none items-center gap-2 rounded-[7px] px-2.5 py-2 text-[12.5px] font-semibold text-petrol outline-none focus:bg-hover dark:text-panel-terminal dark:focus:bg-white/5"
							>
								<Plus className="size-3.5" />
								Add workspace
							</DropdownMenuPrimitive.Item>
						)}
						<DropdownMenuPrimitive.Separator className="mx-2 my-1 h-px bg-hairline dark:bg-white/10" />
						<div className="max-h-64 overflow-y-auto p-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							{filtered.map((workspace) => (
								<DropdownMenuPrimitive.Item
									key={workspace.id}
									disabled={isSwitching}
									onSelect={() => { void choose(workspace.id); }}
									className="group/workspace flex cursor-pointer select-none items-center gap-2.5 rounded-[7px] px-2.5 py-2 text-[12.5px] text-ink outline-none transition-colors focus:bg-hover disabled:opacity-50 dark:text-panel-button dark:focus:bg-white/5"
								>
									<WorkspaceAvatar
										workspaceId={workspace.id}
										name={workspace.name}
										emoji={workspace.emoji}
										color={workspace.color}
										imageRevision={workspace.imageRevision}
										size="xs"
									/>
									<span className="min-w-0 flex-1 truncate font-medium">{workspace.name}</span>
									{workspace.role === "admin" && (
										<Tooltip>
											<TooltipTrigger asChild>
												<button
													type="button"
													aria-label={`Edit ${workspace.name}`}
													onPointerDown={(event) => {
														event.stopPropagation();
													}}
													onPointerUp={(event) => { event.stopPropagation(); }}
													onClick={(event) => {
														event.preventDefault();
														event.stopPropagation();
														edit(workspace.id);
													}}
													onKeyDown={(event) => {
														if (event.key === "Enter" || event.key === " ") {
															event.preventDefault();
															event.stopPropagation();
															edit(workspace.id);
														}
													}}
													className="flex size-6 shrink-0 cursor-pointer items-center justify-center rounded-[6px] text-meta opacity-0 outline-none transition-opacity hover:bg-card hover:text-ink focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-ring/40 group-hover/workspace:opacity-100 group-focus/workspace:opacity-100 dark:hover:bg-white/10"
												>
													<Pencil className="size-3" />
												</button>
											</TooltipTrigger>
											<TooltipContent side="right">Edit workspace</TooltipContent>
										</Tooltip>
									)}
									{workspace.id === activeWorkspaceId && <Check className="size-3.5 shrink-0 text-petrol dark:text-panel-terminal" strokeWidth={3} />}
								</DropdownMenuPrimitive.Item>
							))}
							{filtered.length === 0 && (
								<p className="px-3 py-6 text-center text-[12px] text-meta dark:text-panel-dim">
									No workspace found.
								</p>
							)}
						</div>
					</DropdownMenuPrimitive.Content>
				</DropdownMenuPrimitive.Portal>
			</DropdownMenuPrimitive.Root>
			<CreateWorkspaceDialog open={createOpen} onOpenChange={setCreateOpen} />
			<EditWorkspaceDialog
				key={`${editWorkspaceId ?? "none"}:${editOpen ? "open" : "closed"}`}
				workspace={editWorkspace}
				open={editOpen}
				onOpenChange={setEditOpen}
			/>
		</>
	);
}

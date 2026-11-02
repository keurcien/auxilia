"use client";

import { useEffect, useState, useMemo, useCallback, useRef } from "react";
import {
	X,
	Plus,
	Copy,
	Check,
	Mail,
	ChevronDown,
	MoreVertical,
	Pencil,
	Trash2,
	Users,
	Eye,
	Loader2,
} from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import InviteDialog from "./invite-dialog";
import NewTeamDialog, { type Team } from "./new-team-dialog";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { UserAvatar } from "@/components/ui/user-avatar";
import {
	DataTable,
	DataTablePaginationFooter,
	type DataTableColumn,
} from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { Switch } from "@/components/ui/switch";
import { ViewToggle } from "@/components/ui/view-toggle";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import * as invitesApi from "@/lib/api/resources/invites";
import * as teamsApi from "@/lib/api/resources/teams";
import * as usersApi from "@/lib/api/resources/users";
import * as authApi from "@/lib/api/resources/auth";
import { useUserStore } from "@/stores/user-store";
import { useWorkspacesStore } from "@/stores/workspaces-store";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { usePersistedViewMode } from "@/hooks/use-persisted-view-mode";
import type {
	InstanceUserMembership,
	Invite,
	RoleCounts,
	User,
	UserPromptActivity,
	WorkspaceRole,
} from "@/types/users";
import { workspaceRoleLabel } from "@/lib/user-role";

type Role = WorkspaceRole;
type ListedUser = User & {
	memberships?: InstanceUserMembership[];
};

const PAGE_SIZE = 20;

const ROLE_LABELS: Record<Role, string> = {
	admin: "Admin",
	editor: "Editor",
	member: "Member",
};

// Only the dot is tinted; the role-control chrome stays neutral (design 13c).
const ROLE_DOT: Record<Role, string> = {
	admin: "#1E7A56",
	editor: "#B07A2A",
	member: "#8A9AA0",
};

// Bordered dropdown chip shared by the role and team controls.
const CHIP_CLASS =
	"inline-flex items-center gap-[7px] rounded-[7px] border border-border bg-card px-2.5 py-[5px] text-[12.5px] font-medium text-foreground cursor-pointer transition-colors hover:border-border-hover dark:border-white/10";

const ROLE_FILTERS: { key: "all" | Role; label: string }[] = [
	{ key: "all", label: "All" },
	{ key: "admin", label: "Admins" },
	{ key: "editor", label: "Editors" },
	{ key: "member", label: "Members" },
];

function timeAgo(dateStr: string): string {
	const diff = Date.now() - new Date(dateStr).getTime();
	const days = Math.floor(diff / (1000 * 60 * 60 * 24));
	if (days === 0) return "today";
	if (days === 1) return "1 day ago";
	return `${days} days ago`;
}

function promptTimeAgo(dateStr: string): string {
	const elapsedSeconds = Math.max(
		0,
		Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000),
	);
	if (elapsedSeconds < 60) return "Just now";
	const minutes = Math.floor(elapsedSeconds / 60);
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 30) return `${days}d ago`;
	const months = Math.floor(days / 30);
	if (months < 12) return `${months}mo ago`;
	return `${Math.floor(months / 12)}y ago`;
}

function getInviterShortName(name: string | null): string {
	if (!name) return "Unknown";
	const parts = name.trim().split(" ");
	if (parts.length >= 2) {
		return `${parts[0]} ${parts[parts.length - 1][0]}.`;
	}
	return parts[0];
}

export default function UsersPage() {
	const confirmDialog = useConfirmDialog();
	const currentUser = useUserStore((state) => state.user);
	const activeWorkspaceId = useWorkspacesStore((state) => state.activeWorkspaceId);
	const isAdmin = currentUser?.role === "admin";
	const isOwner = currentUser?.isInstanceOwner === true;
	const fetchUsersTicket = useRef(0);
	const membersTableRef = useRef<HTMLDivElement>(null);
	const [users, setUsers] = useState<ListedUser[]>([]);
	const [promptActivityByUser, setPromptActivityByUser] = useState<
		Record<string, UserPromptActivity>
	>({});
	const [total, setTotal] = useState(0);
	const [offset, setOffset] = useState(0);
	const [roleCounts, setRoleCounts] = useState<RoleCounts | null>(null);
	const [invites, setInvites] = useState<Invite[]>([]);
	const [teams, setTeams] = useState<Team[]>([]);
	const [search, setSearch] = useQueryParamState("q");
	const [viewMode, setViewMode] = usePersistedViewMode("users:view-mode");
	// Seed the debounced value from the restored search so back navigation
	// doesn't flash an unfiltered page before the debounce settles.
	const [debouncedSearch, setDebouncedSearch] = useState(search.trim());
	const [roleFilterParam, setRoleFilter] = useQueryParamState("role", "all");
	const [teamFilterId, setTeamFilterId] = useQueryParamState("team");
	const roleFilter: "all" | Role =
		roleFilterParam === "admin" ||
		roleFilterParam === "editor" ||
		roleFilterParam === "member"
			? roleFilterParam
			: "all";
	const [isLoading, setIsLoading] = useState(true);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
	const [newTeamDialogOpen, setNewTeamDialogOpen] = useState(false);
	const [pendingTeamUserId, setPendingTeamUserId] = useState<string | null>(null);
	const [editingTeam, setEditingTeam] = useState<Team | null>(null);
	const [copiedInviteId, setCopiedInviteId] = useState<string | null>(null);
	const [workspaceListUser, setWorkspaceListUser] =
		useState<ListedUser | null>(null);

	useEffect(() => {
		const timeout = setTimeout(() => {
			setDebouncedSearch(search.trim());
			setOffset(0);
		}, 300);
		return () => {
			clearTimeout(timeout);
		};
	}, [search]);

	const fetchUsers = useCallback(async () => {
		const ticket = ++fetchUsersTicket.current;
		setIsLoading(true);
		try {
			const params = {
				limit: PAGE_SIZE,
				offset,
				...(roleFilter !== "all" && { role: roleFilter }),
				...(debouncedSearch && { search: debouncedSearch }),
				...(teamFilterId && { teamId: teamFilterId }),
			};
			const page = isOwner
				? await usersApi.listInstanceUsers(params)
				: await usersApi.listUsers(params);
			if (ticket !== fetchUsersTicket.current) return;
			setUsers(
				page.items.map((user) => {
					if (!("memberships" in user)) return user;
					const activeMembership =
						user.memberships.find(
							(membership) =>
								membership.workspaceId === activeWorkspaceId,
						) ?? user.memberships[0];
					return {
						...user,
						role: activeMembership?.role ?? "member",
						teamId: activeMembership?.teamId ?? null,
					};
				}),
			);
			setTotal(page.total);
		} catch (error) {
			if (ticket !== fetchUsersTicket.current) return;
			console.error("Error fetching users:", error);
		} finally {
			if (ticket === fetchUsersTicket.current) setIsLoading(false);
		}
	}, [
		offset,
		roleFilter,
		debouncedSearch,
		teamFilterId,
		isOwner,
		activeWorkspaceId,
	]);

	const fetchRoleCounts = useCallback(async () => {
		if (isOwner) {
			setRoleCounts(null);
			return;
		}
		try {
			setRoleCounts(await usersApi.getRoleCounts());
		} catch (error) {
			console.error("Error fetching role counts:", error);
		}
	}, [isOwner]);

	const fetchTeams = useCallback(async () => {
		try {
			setTeams(await teamsApi.listTeams());
		} catch (error) {
			console.error("Error fetching teams:", error);
		}
	}, []);

	useEffect(() => {
		void fetchUsers();
	}, [fetchUsers]);

	const visibleUserIds = useMemo(() => users.map((user) => user.id), [users]);

	useEffect(() => {
		if (!isAdmin || visibleUserIds.length === 0) return;
		let cancelled = false;

		const refreshPromptActivity = async () => {
			try {
				const activity = await usersApi.getPromptActivity(visibleUserIds);
				if (cancelled) return;
				setPromptActivityByUser(
					Object.fromEntries(activity.map((item) => [item.userId, item])),
				);
			} catch (error) {
				if (!cancelled) {
					console.error("Error fetching prompt activity:", error);
				}
			}
		};

		void refreshPromptActivity();
		const interval = window.setInterval(() => {
			void refreshPromptActivity();
		}, 5000);
		return () => {
			cancelled = true;
			window.clearInterval(interval);
		};
	}, [isAdmin, visibleUserIds]);

	useEffect(() => {
		void fetchRoleCounts();
		void fetchTeams();
		const fetchInvites = async () => {
			try {
				setInvites(await invitesApi.listInvites());
			} catch (error) {
				console.error("Error fetching invites:", error);
			}
		};
		void fetchInvites();
	}, [fetchRoleCounts, fetchTeams]);

	const teamsById = useMemo(
		() => new Map(teams.map((t) => [t.id, t])),
		[teams],
	);
	const filteredTeam = teamFilterId ? teamsById.get(teamFilterId) : undefined;

	const handleRoleFilterChange = (key: "all" | Role) => {
		setRoleFilter(key);
		setOffset(0);
	};

	const handleCopyInviteLink = async (invite: Invite) => {
		if (!invite.inviteUrl) return;
		await navigator.clipboard.writeText(invite.inviteUrl);
		setCopiedInviteId(invite.id);
		setTimeout(() => { setCopiedInviteId(null); }, 2000);
	};

	const handleDeleteInvite = async (inviteId: string) => {
		try {
			await invitesApi.deleteInvite(inviteId);
			setInvites((prev) => prev.filter((i) => i.id !== inviteId));
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error deleting invite:", error);
			}
		}
	};

	const handleRoleChange = async (userId: string, newRole: Role) => {
		try {
			await usersApi.setUserRole(userId, newRole);
			if (roleFilter === "all") {
				setUsers((prev) =>
					prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u)),
				);
			} else {
				// The row may no longer match the active filter — resync the page.
				void fetchUsers();
			}
			void fetchRoleCounts();
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error updating role:", error);
			}
		}
	};

	const handleWorkspaceCreationChange = async (userId: string, allowed: boolean) => {
		try {
			const updated = await usersApi.setCanCreateWorkspace(userId, allowed);
			setUsers((previous) =>
				previous.map((user) =>
					user.id === userId ? { ...user, ...updated } : user,
				),
			);
			if (userId === currentUser?.id) {
				useUserStore.getState().setUser({ ...currentUser, canCreateWorkspace: allowed });
			}
		} catch {
			setErrorDialogOpen(true);
		}
	};

	const handleThreadDeletionChange = async (userId: string, allowed: boolean) => {
		try {
			const updated = await usersApi.setCanDeleteThreads(userId, allowed);
			setUsers((previous) =>
				previous.map((user) =>
					user.id === userId ? { ...user, ...updated } : user,
				),
			);
			if (userId === currentUser?.id) {
				useUserStore
					.getState()
					.setUser({ ...currentUser, canDeleteThreads: allowed });
			}
		} catch {
			setErrorDialogOpen(true);
		}
	};

	const handleTeamChange = async (userId: string, teamId: string | null) => {
		try {
			await usersApi.setUserTeam(userId, teamId);
			setUsers((prev) =>
				prev.map((u) => (u.id === userId ? { ...u, teamId } : u)),
			);
			// Team member counts come from the backend — resync them.
			void fetchTeams();
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error updating team:", error);
			}
		}
	};

	const handleOpenNewTeam = (userId: string) => {
		setEditingTeam(null);
		setPendingTeamUserId(userId);
		setNewTeamDialogOpen(true);
	};

	const handleTeamCreated = (team: Team) => {
		setTeams((prev) =>
			[...prev, team].sort((a, b) => a.name.localeCompare(b.name)),
		);
		if (pendingTeamUserId) {
			void handleTeamChange(pendingTeamUserId, team.id);
			setPendingTeamUserId(null);
		}
	};

	const handleTeamUpdated = (team: Team) => {
		// The PATCH response reports memberCount 0 — keep the count we have.
		setTeams((prev) =>
			prev
				.map((t) => (t.id === team.id ? { ...team, memberCount: t.memberCount } : t))
				.sort((a, b) => a.name.localeCompare(b.name)),
		);
	};

	const openCreateTeam = () => {
		setEditingTeam(null);
		setPendingTeamUserId(null);
		setNewTeamDialogOpen(true);
	};

	const openEditTeam = (team: Team) => {
		setEditingTeam(team);
		setPendingTeamUserId(null);
		setNewTeamDialogOpen(true);
	};

	const handleViewTeamMembers = (team: Team) => {
		setSearch("");
		setRoleFilter("all");
		setTeamFilterId(team.id);
		setOffset(0);
		requestAnimationFrame(() => {
			membersTableRef.current?.scrollIntoView({
				behavior: "smooth",
				block: "start",
			});
		});
	};

	const handleDeleteTeam = async (team: Team) => {
		const memberCount = team.memberCount;
		const confirmed = await confirmDialog({
			title: `Delete “${team.name}”?`,
			description:
				memberCount > 0
					? `${memberCount} member${memberCount === 1 ? "" : "s"} will be unassigned and the team’s agent links will be removed.`
					: "The team’s agent links will be removed. This action cannot be undone.",
			confirmLabel: "Delete team",
			destructive: true,
		});
		if (!confirmed) return;

		try {
			await teamsApi.deleteTeam(team.id);
			setTeams((prev) => prev.filter((t) => t.id !== team.id));
			if (teamFilterId === team.id) {
				setTeamFilterId("");
			}
			// Mirror the DB's ON DELETE SET NULL so the table reflects reality.
			setUsers((prev) =>
				prev.map((u) => (u.teamId === team.id ? { ...u, teamId: null } : u)),
			);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error deleting team:", error);
			}
		}
	};

	const handleRemoveUser = async (userId: string, userName: string | null) => {
		const confirmed = await confirmDialog({
			title: `Remove ${userName || "this user"}?`,
			description:
				"They will lose access to this workspace and its shared resources.",
			confirmLabel: "Remove user",
			destructive: true,
		});
		if (!confirmed) return;

		try {
			await usersApi.deleteUser(userId);
			// Resync page, counts and team membership from the server.
			void fetchUsers();
			void fetchRoleCounts();
			void fetchTeams();
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error removing user:", error);
			}
		}
	};

	const handleSupervise = async (
		user: ListedUser,
		membership: InstanceUserMembership,
	) => {
		const displayName = user.name || user.email || "this user";
		const confirmed = await confirmDialog({
			title: `Supervise as ${displayName}?`,
			description: `You will act with this user’s permissions in ${membership.workspaceName}. An orange banner will remain visible until you exit supervision.`,
			confirmLabel: "Start supervision",
		});
		if (!confirmed) return;
		try {
			await authApi.startSupervision(user.id, membership.workspaceId);
			window.location.assign("/agents");
		} catch (error) {
			console.error("Error starting supervision:", error);
			setErrorDialogOpen(true);
		}
	};

	const supervisionItems = (user: ListedUser) =>
		(user.memberships ?? []).map((membership) => ({
			label:
				(user.memberships?.length ?? 0) > 1
					? `Supervise in ${membership.workspaceName}`
					: "Supervise as user",
			icon: <Eye />,
			onClick: () => {
				void handleSupervise(user, membership);
			},
		}));

	const renderRoleControl = (user: ListedUser) => {
		if (isOwner) {
			return (
				<div className="flex flex-col items-start gap-1.5">
					{user.isInstanceOwner && (
						<span className="inline-flex rounded-full bg-amber-500/12 px-2.5 py-1 text-[11.5px] font-semibold text-amber-800 dark:bg-amber-400/15 dark:text-amber-200">
							Owner
						</span>
					)}
					{!user.isInstanceOwner &&
						(user.memberships ?? []).map((membership) => (
							<span
								key={membership.workspaceId}
								className="inline-flex items-center gap-[7px] text-[12px] font-medium text-subtle dark:text-muted-foreground"
							>
								<span
									className="size-1.5 rounded-full"
									style={{ background: ROLE_DOT[membership.role] }}
								/>
								{workspaceRoleLabel(membership.role)}
							</span>
						))}
				</div>
			);
		}
		const isCurrentUser = user.id === currentUser?.id;
		return isCurrentUser || !isAdmin ? (
			<span className="inline-flex items-center gap-[7px] px-2.5 py-[5px] text-[12.5px] font-medium text-subtle dark:text-muted-foreground">
				<span
					className="size-1.5 rounded-full"
					style={{ background: ROLE_DOT[user.role] }}
				/>
				{ROLE_LABELS[user.role]}
			</span>
		) : (
			<DropdownMenu
				trigger={
					<button className={CHIP_CLASS}>
						<span
							className="size-1.5 rounded-full"
							style={{ background: ROLE_DOT[user.role] }}
						/>
						{ROLE_LABELS[user.role]}
						<ChevronDown className="size-3.5 text-meta" />
					</button>
				}
				items={[
					{
						label: "Admin",
						onClick: () => {
							void handleRoleChange(user.id, "admin");
						},
						active: user.role === "admin",
					},
					{
						label: "Editor",
						onClick: () => {
							void handleRoleChange(user.id, "editor");
						},
						active: user.role === "editor",
					},
					{
						label: "Member",
						onClick: () => {
							void handleRoleChange(user.id, "member");
						},
						active: user.role === "member",
					},
				]}
			/>
		);
	};

	const renderWorkspaceCreationControl = (user: ListedUser) => (
		<div className="flex items-center gap-2">
			<Switch
				checked={user.isInstanceOwner || user.canCreateWorkspace}
				disabled={
					user.isInstanceOwner ||
					currentUser?.role !== "admin" ||
					(Boolean(user.memberships) &&
						!user.memberships?.some(
							(membership) =>
								membership.workspaceId === activeWorkspaceId,
						))
				}
				onCheckedChange={(checked) => {
					void handleWorkspaceCreationChange(user.id, checked);
				}}
				aria-label={`Allow ${user.name ?? user.email ?? "user"} to create workspaces`}
			/>
			<span className="text-[11px] text-meta">
				{user.isInstanceOwner
					? "Owner"
					: user.canCreateWorkspace
						? "Allowed"
						: "No"}
			</span>
		</div>
	);

	const renderThreadDeletionControl = (user: ListedUser) => (
		<div className="flex items-center gap-2">
			<Switch
				checked={user.canDeleteThreads}
				disabled={
					currentUser?.role !== "admin" ||
					(Boolean(user.memberships) &&
						!user.memberships?.some(
							(membership) =>
								membership.workspaceId === activeWorkspaceId,
						))
				}
				onCheckedChange={(checked) => {
					void handleThreadDeletionChange(user.id, checked);
				}}
				aria-label={`Allow ${user.name ?? user.email ?? "user"} to delete conversations`}
			/>
			<span className="text-[11px] text-meta">
				{user.canDeleteThreads ? "Allowed" : "No"}
			</span>
		</div>
	);

	const renderTeamControl = (user: User) => {
		const team = user.teamId ? teamsById.get(user.teamId) : undefined;
		if (!isAdmin) {
			return (
				<span className="text-[12.5px] font-medium text-subtle dark:text-muted-foreground">
					{team?.name ?? "No team"}
				</span>
			);
		}
		return (
			<DropdownMenu
				align="start"
				trigger={
					team ? (
						<button className={`${CHIP_CLASS} max-w-full`}>
							<span
								className="size-1.5 shrink-0 rounded-full"
								style={{ background: team.color ?? "#9E9E9E" }}
							/>
							<span className="truncate">{team.name}</span>
							<ChevronDown className="size-3.5 shrink-0 text-meta" />
						</button>
					) : (
						<button className="inline-flex cursor-pointer items-center gap-[7px] rounded-[7px] border border-dashed border-input bg-transparent px-2.5 py-[5px] text-[12.5px] font-medium text-meta transition-colors hover:border-border-hover hover:text-subtle dark:border-white/15">
							<span className="size-1.5 shrink-0 rounded-full border border-faint dark:border-white/20" />
							No team
							<ChevronDown className="size-3.5 shrink-0 text-meta" />
						</button>
					)
				}
				items={[
					{
						label: "No team",
						icon: (
							<span className="block size-2 rounded-full border border-[#c3d2cb] dark:border-white/25" />
						),
						onClick: () => {
							void handleTeamChange(user.id, null);
						},
						active: !user.teamId,
					},
					...teams.map((candidate) => ({
						label: candidate.name,
						icon: (
							<span
								className="block size-2 rounded-full"
								style={{ background: candidate.color ?? "#9E9E9E" }}
							/>
						),
						onClick: () => {
							void handleTeamChange(user.id, candidate.id);
						},
						active: user.teamId === candidate.id,
					})),
					{ separator: true as const },
					{
						label: "New team",
						icon: <Plus />,
						onClick: () => {
							handleOpenNewTeam(user.id);
						},
					},
				]}
			/>
		);
	};

	const renderPromptActivity = (user: ListedUser) => {
		const activity = promptActivityByUser[user.id];
		if (!activity) {
			return <span className="text-[12px] text-meta">Loading…</span>;
		}
		return (
			<div className="flex items-center gap-1.5">
				<span
					className="font-mono text-[11.5px] text-subtle dark:text-muted-foreground"
					title={
						activity.lastPromptAt
							? new Date(activity.lastPromptAt).toLocaleString()
							: undefined
					}
				>
					{activity.lastPromptAt
						? promptTimeAgo(activity.lastPromptAt)
						: "Never"}
				</span>
				{activity.hasActivePrompt && (
					<Loader2
						className="size-3.5 shrink-0 animate-spin text-petrol motion-reduce:animate-none"
						aria-label="Prompt is running"
					/>
				)}
			</div>
		);
	};

	const columns: DataTableColumn<ListedUser>[] = [
		{
			key: "name",
			header: "Name",
			width: "minmax(220px, 1.4fr)",
			cell: (user) => {
				const isCurrentUser = user.id === currentUser?.id;
				return (
					<div className="flex min-w-0 items-center gap-3">
						<UserAvatar
							name={user.name}
							pictureUrl={user.pictureUrl}
							userId={user.id}
							imageRevision={user.imageRevision}
							className="shrink-0"
						/>
						<div className="min-w-0">
							<div className="flex min-w-0 items-center gap-2">
								<span className="truncate text-[13.5px] font-semibold text-foreground">
									{user.name || "Unnamed"}
								</span>
								{isCurrentUser && (
									<span className="shrink-0 rounded-[4px] bg-petrol-tint px-1.5 py-0.5 text-[9px] font-bold text-petrol dark:bg-white/10 dark:text-panel-terminal">
										You
									</span>
								)}
							</div>
						</div>
					</div>
				);
			},
		},
		{
			key: "email",
			header: "Email",
			width: "230px",
			cell: (user) => (
				<span className="block truncate font-mono text-[11.5px] text-subtle dark:text-muted-foreground">
					{user.email}
				</span>
			),
		},
		...(isAdmin
			? [
					{
						key: "last-prompt",
						header: "Last prompt",
						width: "130px",
						cell: renderPromptActivity,
					},
				]
			: []),
		...(isOwner
			? [
					{
						key: "workspaces",
						header: "Workspaces",
						width: "110px",
						align: "center" as const,
						cell: (user: ListedUser) => (
							<button
								type="button"
								aria-label={`View workspaces for ${user.name || user.email || "user"}`}
								onClick={() => {
									setWorkspaceListUser(user);
								}}
								className="mx-auto flex size-8 cursor-pointer items-center justify-center rounded-full bg-hover font-mono text-[11px] font-semibold text-label transition-colors hover:bg-petrol-tint hover:text-petrol dark:bg-white/5 dark:text-panel-body dark:hover:bg-white/10 dark:hover:text-panel-terminal"
							>
								{user.memberships?.length ?? 0}
							</button>
						),
					},
				]
			: []),
		{
			key: "role",
			header: "Role",
			width: "130px",
			mobileWidth: "auto",
			cell: renderRoleControl,
		},
		{
			key: "can-create-workspace",
			header: "Create workspaces",
			width: "150px",
			mobileWidth: "auto",
			cell: renderWorkspaceCreationControl,
		},
		{
			key: "can-delete-threads",
			header: "Delete conversations",
			width: "165px",
			mobileWidth: "auto",
			cell: renderThreadDeletionControl,
		},
		...(!isOwner
			? [
					{
						key: "team",
						header: "Team",
						width: "160px",
						cell: renderTeamControl,
					},
				]
			: []),
		{
			key: "actions",
			header: "",
			width: "36px",
			cell: (user) => {
				const isCurrentUser = user.id === currentUser?.id;
				return (
					<div className="flex justify-center">
						{isOwner &&
							!isCurrentUser &&
							(user.memberships?.length ?? 0) > 0 && (
							<DropdownMenu
								trigger={
									<button
										type="button"
										aria-label={`Actions for ${user.name || user.email || "user"}`}
										className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover dark:hover:bg-white/10"
									>
										<MoreVertical className="size-[16px]" />
									</button>
								}
								items={supervisionItems(user)}
							/>
						)}
						{!isOwner && isAdmin && !isCurrentUser && (
							<button
								type="button"
								aria-label={`Remove ${user.name || user.email || "user"}`}
								className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-ghost opacity-100 transition-all hover:bg-[#FBEFED] hover:text-[#B04A3A] md:opacity-0 md:group-hover:opacity-100 dark:hover:bg-rose-950"
								onClick={() => { void handleRemoveUser(user.id, user.name); }}
							>
								<X className="size-[15px]" />
							</button>
						)}
					</div>
				);
			},
		},
	];

	return (
		<WorkspacePage
			slug="users"
			title="Users"
			intro={
				isOwner
					? "Supervise users across the instance and review their workspace access."
					: "Manage who's in your workspace and what they can do."
			}
			search={{
				placeholder: "Search users…",
				value: search,
				onChange: setSearch,
			}}
			actions={isAdmin ? (
				<WorkspaceTopBarButton
					aria-label="Invite user"
					title="Invite user"
					className="size-9 justify-center p-0 lg:h-auto lg:w-auto lg:px-[18px] lg:py-[9px]"
					onClick={() => {
						setInviteDialogOpen(true);
					}}
				>
					<Plus className="size-3.5" />
					<span className="hidden lg:inline">Invite user</span>
				</WorkspaceTopBarButton>
			) : undefined}
		>
			<Dialog
				open={workspaceListUser !== null}
				onOpenChange={(open) => {
					if (!open) setWorkspaceListUser(null);
				}}
			>
				<DialogContent className="gap-4 sm:max-w-[440px]">
					<DialogHeader>
						<DialogTitle>
							{workspaceListUser?.name ||
								workspaceListUser?.email ||
								"User"}{" "}
							workspaces
						</DialogTitle>
						<DialogDescription>
							{workspaceListUser?.memberships?.length ?? 0} workspace
							{workspaceListUser?.memberships?.length === 1 ? "" : "s"}
						</DialogDescription>
					</DialogHeader>
					<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
						{workspaceListUser?.memberships?.map((membership) => (
							<div
								key={membership.workspaceId}
								className="flex items-center justify-between gap-4 border-b border-hairline px-3.5 py-3 last:border-b-0 dark:border-white/5"
							>
								<span className="min-w-0 truncate text-[13px] font-semibold text-foreground">
									{membership.workspaceName}
								</span>
								<span className="shrink-0 rounded-full bg-hover px-2.5 py-1 text-[11px] font-medium text-label dark:bg-white/5 dark:text-panel-body">
									{workspaceRoleLabel(membership.role)}
								</span>
							</div>
						))}
					</div>
				</DialogContent>
			</Dialog>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			{isAdmin && (
				<InviteDialog
					open={inviteDialogOpen}
					onOpenChange={setInviteDialogOpen}
					onInviteCreated={(invite) => {
						if (invite.workspaceId === activeWorkspaceId) {
							setInvites((prev) => [...prev, invite]);
						}
					}}
				/>
			)}
			{isAdmin && newTeamDialogOpen && (
				<NewTeamDialog
					open
					onOpenChange={(open) => {
						setNewTeamDialogOpen(open);
						if (!open) {
							setPendingTeamUserId(null);
							setEditingTeam(null);
						}
					}}
					team={editingTeam}
					onTeamCreated={handleTeamCreated}
					onTeamUpdated={handleTeamUpdated}
				/>
			)}
			{/* Role filter chips (design 13c: pills above the table) */}
			<div className="flex flex-wrap items-center gap-2 pb-[18px] pt-1.5">
				{ROLE_FILTERS.map((filter) => {
					const active = roleFilter === filter.key;
					const count =
						filter.key === "all"
							? isOwner
								? total
								: roleCounts?.total
							: roleCounts?.[filter.key];
					return (
						<button
							key={filter.key}
							type="button"
							onClick={() => {
								handleRoleFilterChange(filter.key);
							}}
							className={
								active
									? "inline-flex cursor-pointer items-center gap-[7px] rounded-full bg-petrol-tint px-[13px] py-1.5 text-[12.5px] font-semibold text-petrol dark:bg-white/10 dark:text-panel-terminal"
									: "inline-flex cursor-pointer items-center gap-[7px] rounded-full border border-border px-[13px] py-1.5 text-[12.5px] font-medium text-subtle transition-colors hover:bg-sidebar dark:border-white/10 dark:text-panel-body dark:hover:bg-white/5"
							}
						>
							{filter.label}
							{count !== undefined && (
								<span
									className={`font-mono text-[10.5px] ${active ? "opacity-70" : "text-meta dark:text-panel-dim"}`}
								>
									{count}
								</span>
							)}
						</button>
					);
				})}
				{teamFilterId && (
					<button
						type="button"
						aria-label={`Clear ${filteredTeam?.name ?? "team"} filter`}
						onClick={() => {
							setTeamFilterId("");
							setOffset(0);
						}}
						className="inline-flex cursor-pointer items-center gap-[7px] rounded-full bg-petrol-tint px-[13px] py-1.5 text-[12.5px] font-semibold text-petrol dark:bg-white/10 dark:text-panel-terminal"
					>
						<span
							className="size-1.5 rounded-full"
							style={{ background: filteredTeam?.color ?? "#9E9E9E" }}
						/>
						{filteredTeam?.name ?? "Team"}
						<X className="size-3.5 opacity-70" />
					</button>
				)}
				<ViewToggle
					value={viewMode}
					onChange={setViewMode}
					className="ml-auto"
				/>
			</div>

			{/* Member list */}
			<div ref={membersTableRef} className="scroll-mt-4">
				{viewMode === "table" ? (
					<DataTable
						columns={columns}
						rows={users}
						rowKey={(user) => user.id}
						isLoading={isLoading}
						minTableWidth={
							isOwner ? (isAdmin ? "1250px" : "1120px") : isAdmin ? "1180px" : "1050px"
						}
						bleedOnNarrow
						emptyMessage={
							debouncedSearch || roleFilter !== "all" || teamFilterId
								? "No users match your filters."
								: isOwner
									? "No users in this instance."
									: "No members in this workspace."
						}
						pagination={{
							total,
							limit: PAGE_SIZE,
							offset,
							onOffsetChange: setOffset,
							itemLabel: total === 1 ? "user" : "users",
						}}
					/>
				) : isLoading && users.length === 0 ? (
					<div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
						{Array.from({ length: 6 }, (_, index) => (
							<div
								key={index}
								className="h-[220px] animate-pulse rounded-xl border border-border bg-card dark:border-white/10"
							/>
						))}
					</div>
				) : users.length === 0 ? (
					<div className="flex min-h-48 items-center justify-center rounded-[10px] border border-dashed border-border px-6 text-center text-[13px] text-subtle">
						{debouncedSearch || roleFilter !== "all" || teamFilterId
							? "No users match your filters."
							: isOwner
								? "No users in this instance."
								: "No members in this workspace."}
					</div>
				) : (
					<>
						<div
							className={`grid grid-cols-1 gap-3 transition-opacity sm:grid-cols-2 xl:grid-cols-3 ${
								isLoading ? "opacity-60" : ""
							}`}
						>
							{users.map((user) => {
								const isCurrentUser = user.id === currentUser?.id;
								return (
									<article
										key={user.id}
										className="group flex min-h-[220px] flex-col rounded-xl border border-[#e1ebe6] bg-card p-4 transition-[border-color,box-shadow] hover:border-[#cfe0d8] hover:shadow-[0_3px_10px_rgba(30,45,40,0.06)] dark:border-white/10 dark:hover:border-white/20"
									>
										<div className="flex min-w-0 items-start gap-3">
											<UserAvatar
												name={user.name}
												pictureUrl={user.pictureUrl}
												userId={user.id}
												imageRevision={user.imageRevision}
												className="shrink-0"
											/>
											<div className="min-w-0 flex-1">
												<div className="flex min-w-0 items-center gap-2">
													<h2 className="truncate text-[13.5px] font-semibold text-foreground">
														{user.name || "Unnamed"}
													</h2>
													{isCurrentUser && (
														<span className="shrink-0 rounded-[4px] bg-petrol-tint px-1.5 py-0.5 text-[9px] font-bold text-petrol dark:bg-white/10 dark:text-panel-terminal">
															You
														</span>
													)}
												</div>
												<p className="mt-0.5 truncate font-mono text-[11.5px] text-subtle dark:text-muted-foreground">
													{user.email}
												</p>
											</div>
											{isOwner &&
												!isCurrentUser &&
												(user.memberships?.length ?? 0) > 0 && (
													<DropdownMenu
														trigger={
															<button
																type="button"
																aria-label={`Actions for ${user.name || user.email || "user"}`}
																className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-colors hover:bg-hover dark:hover:bg-white/10"
															>
																<MoreVertical className="size-[16px]" />
															</button>
														}
														items={supervisionItems(user)}
													/>
												)}
											{!isOwner && isAdmin && !isCurrentUser && (
												<button
													type="button"
													aria-label={`Remove ${user.name || user.email || "user"}`}
													className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-ghost transition-colors hover:bg-[#FBEFED] hover:text-[#B04A3A] dark:hover:bg-rose-950"
													onClick={() => {
														void handleRemoveUser(user.id, user.name);
													}}
												>
													<X className="size-[15px]" />
												</button>
											)}
										</div>
										<div className="mt-5 grid grid-cols-2 gap-x-3 gap-y-4">
											{isOwner ? (
												<div className="col-span-2 min-w-0">
													<p className="mb-1.5 text-[10px] font-semibold text-meta">
														Workspace access
													</p>
													<div className="space-y-1.5">
														{user.isInstanceOwner && (
															<span className="inline-flex rounded-full bg-amber-500/12 px-2.5 py-1 text-[11.5px] font-semibold text-amber-800 dark:bg-amber-400/15 dark:text-amber-200">
																Owner
															</span>
														)}
														{(user.memberships ?? []).map((membership) => (
															<div
																key={membership.workspaceId}
																className="flex items-center justify-between gap-3 text-[11.5px]"
															>
																<span className="truncate font-medium text-label">
																	{membership.workspaceName}
																</span>
																<span className="shrink-0 text-meta">
																	{workspaceRoleLabel(membership.role)}
																</span>
															</div>
														))}
													</div>
												</div>
											) : (
												<>
													<div className="min-w-0">
														<p className="mb-1.5 text-[10px] font-semibold text-meta">
															Role
														</p>
														{renderRoleControl(user)}
													</div>
													<div className="min-w-0">
														<p className="mb-1.5 text-[10px] font-semibold text-meta">
															Team
														</p>
														{renderTeamControl(user)}
													</div>
												</>
											)}
											{isAdmin && (
												<div className="col-span-2 min-w-0">
													<p className="mb-1.5 text-[10px] font-semibold text-meta">
														Last prompt
													</p>
													{renderPromptActivity(user)}
												</div>
											)}
											<div className="col-span-2 mt-auto grid grid-cols-2 gap-3 border-t border-hairline pt-3 dark:border-white/5">
												<div>
													<p className="mb-1.5 text-[10px] font-semibold text-meta">
														Create workspaces
													</p>
													{renderWorkspaceCreationControl(user)}
												</div>
												<div>
													<p className="mb-1.5 text-[10px] font-semibold text-meta">
														Delete conversations
													</p>
													{renderThreadDeletionControl(user)}
												</div>
											</div>
										</div>
									</article>
								);
							})}
						</div>
						<DataTablePaginationFooter
							total={total}
							limit={PAGE_SIZE}
							offset={offset}
							onOffsetChange={setOffset}
							itemLabel={total === 1 ? "user" : "users"}
						/>
					</>
				)}
			</div>

			{/* Teams */}
			<div className="flex items-baseline gap-2.5 pt-[18px] pb-3">
				<span className="text-[14px] font-bold tracking-[-0.01em] text-foreground">
					Teams
				</span>
				<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
					{teams.length}
				</span>
				<span className="h-px flex-1 self-center bg-border dark:bg-white/10" />
				{isAdmin && (
					<button
						onClick={openCreateTeam}
						className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-border px-3 py-1.5 text-[12px] font-semibold text-subtle transition-colors hover:bg-sidebar dark:border-white/10 dark:text-muted-foreground dark:hover:bg-white/5"
					>
						<Plus className="size-3.5" />
						New team
					</button>
				)}
			</div>

			{teams.length === 0 ? (
				<div className="rounded-[10px] border border-dashed border-input bg-transparent px-[18px] py-8 text-center text-[14px] font-medium text-faint dark:border-white/10 dark:text-muted-foreground">
					No teams yet. Create one to group members.
				</div>
			) : (
				<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
					{teams.map((team) => (
						<div
							key={team.id}
							className="group flex items-center gap-3 border-b border-hairline px-4 py-[11px] transition-colors duration-[110ms] last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5"
						>
							<span
								className="block size-[9px] shrink-0 rounded-full"
								style={{ background: team.color ?? "#9E9E9E" }}
							/>
							<span className="flex-1 truncate text-[13.5px] font-semibold text-foreground">
								{team.name}
							</span>
							<span className="shrink-0 text-[10.5px] text-meta dark:text-panel-dim">
								<span className="font-mono">{team.memberCount}</span> member
								{team.memberCount === 1 ? "" : "s"}
							</span>
							{isAdmin && (
								<DropdownMenu
									trigger={
										<button className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-all hover:bg-hover md:opacity-0 md:group-hover:opacity-100 dark:hover:bg-white/10">
											<MoreVertical className="size-[18px]" />
										</button>
									}
									items={[
										{
											label: "View Members",
											icon: <Users />,
											onClick: () => {
												handleViewTeamMembers(team);
											},
										},
										{ separator: true },
										{
											label: "Rename",
											icon: <Pencil />,
											onClick: () => { openEditTeam(team); },
										},
										{
											label: "Delete",
											icon: <Trash2 />,
											destructive: true,
											onClick: () => {
												void handleDeleteTeam(team);
											},
										},
									]}
								/>
							)}
						</div>
					))}
				</div>
			)}

			{/* Pending invites */}
			{invites.length > 0 && (
				<>
					<div className="flex items-baseline gap-2.5 pt-[22px] pb-3">
						<span className="text-[14px] font-bold tracking-[-0.01em] text-foreground">
							Pending invites
						</span>
						<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
							{invites.length}
						</span>
						<span className="h-px flex-1 self-center bg-border dark:bg-white/10" />
					</div>

					<div className="overflow-hidden rounded-[10px] border border-border bg-card dark:border-white/10">
						{invites.map((invite) => (
							<div
								key={invite.id}
								className="flex flex-col gap-3 border-b border-hairline px-4 py-[11px] last:border-b-0 md:grid md:grid-cols-[1fr_150px_auto] md:items-center md:gap-4 dark:border-white/5"
							>
								{/* Envelope + email + meta */}
								<div className="flex min-w-0 items-center gap-3">
									<span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-dashed border-input text-meta dark:border-white/15">
										<Mail className="size-[14px]" />
									</span>
									<div className="min-w-0">
										<div className="truncate font-mono text-[12px] font-medium text-foreground">
											{invite.email}
										</div>
										<div className="mt-0.5 truncate text-[11.5px] text-meta dark:text-panel-dim">
											Invited {timeAgo(invite.createdAt)}, by{" "}
											{getInviterShortName(invite.invitedByName)}
										</div>
									</div>
								</div>

								{/* Status pill */}
								<span className="inline-flex w-fit items-center gap-1.5 rounded-[4px] bg-warning-bg px-2.5 py-1 text-[11px] font-semibold text-warning dark:bg-amber-950 dark:text-amber-300">
									<span className="size-[5px] rounded-full bg-warning" />
									{invite.role in ROLE_LABELS
										? ROLE_LABELS[invite.role as Role]
										: invite.role}{" "}
									invite
								</span>

								{/* Actions */}
								<div className="flex items-center gap-1.5">
									{invite.inviteUrl && (
										<button
											className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-border px-3 py-1.5 text-[12px] font-medium text-subtle transition-colors hover:bg-sidebar dark:border-white/10 dark:text-muted-foreground dark:hover:bg-white/5"
											onClick={() => { void handleCopyInviteLink(invite); }}
										>
											{copiedInviteId === invite.id ? (
												<Check className="size-3.5" />
											) : (
												<Copy className="size-3.5" />
											)}
											{copiedInviteId === invite.id ? "Copied!" : "Copy link"}
										</button>
									)}
									{isAdmin && (
										<button
											className="cursor-pointer rounded-[7px] border border-border px-3 py-1.5 text-[12px] font-medium text-[#B04A3A] transition-colors hover:bg-[#FBEFED] dark:border-white/10 dark:hover:bg-rose-950"
											onClick={() => { void handleDeleteInvite(invite.id); }}
										>
											Revoke
										</button>
									)}
								</div>
							</div>
						))}
					</div>
				</>
			)}
		</WorkspacePage>
	);
}

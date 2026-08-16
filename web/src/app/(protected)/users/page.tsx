"use client";

import { useEffect, useState, useMemo, useCallback } from "react";
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
} from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import InviteDialog from "./invite-dialog";
import NewTeamDialog, { type Team } from "./new-team-dialog";
import {
	WorkspacePage,
	WorkspaceTopBarButton,
} from "@/components/layout/workspace-page";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api/client";
import { useUserStore } from "@/stores/user-store";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import type { Paginated } from "@/types/api";

interface User {
	id: string;
	name: string | null;
	email: string | null;
	role: "member" | "editor" | "admin";
	teamId: string | null;
	createdAt: string;
	updatedAt: string;
}

interface Invite {
	id: string;
	email: string;
	role: string;
	inviteUrl: string;
	invitedByName: string | null;
	createdAt: string;
}

interface RoleCounts {
	total: number;
	member: number;
	editor: number;
	admin: number;
}

type Role = "member" | "editor" | "admin";

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

function getInitials(name: string | null | undefined): string {
	if (!name) return "U";
	const parts = name.trim().split(" ");
	if (parts.length >= 2) {
		return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
	}
	return name.substring(0, 2).toUpperCase();
}

function timeAgo(dateStr: string): string {
	const diff = Date.now() - new Date(dateStr).getTime();
	const days = Math.floor(diff / (1000 * 60 * 60 * 24));
	if (days === 0) return "today";
	if (days === 1) return "1 day ago";
	return `${days} days ago`;
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
	const currentUser = useUserStore((state) => state.user);
	const [users, setUsers] = useState<User[]>([]);
	const [total, setTotal] = useState(0);
	const [offset, setOffset] = useState(0);
	const [roleCounts, setRoleCounts] = useState<RoleCounts | null>(null);
	const [invites, setInvites] = useState<Invite[]>([]);
	const [teams, setTeams] = useState<Team[]>([]);
	const [search, setSearch] = useQueryParamState("q");
	// Seed the debounced value from the restored search so back navigation
	// doesn't flash an unfiltered page before the debounce settles.
	const [debouncedSearch, setDebouncedSearch] = useState(search.trim());
	const [roleFilterParam, setRoleFilter] = useQueryParamState("role", "all");
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
		setIsLoading(true);
		try {
			const response = await api.get<Paginated<User>>("/users", {
				params: {
					limit: PAGE_SIZE,
					offset,
					...(roleFilter !== "all" && { role: roleFilter }),
					...(debouncedSearch && { search: debouncedSearch }),
				},
			});
			setUsers(response.data.items);
			setTotal(response.data.total);
		} catch (error) {
			console.error("Error fetching users:", error);
		} finally {
			setIsLoading(false);
		}
	}, [offset, roleFilter, debouncedSearch]);

	const fetchRoleCounts = useCallback(async () => {
		try {
			const response = await api.get<RoleCounts>("/users/role-counts");
			setRoleCounts(response.data);
		} catch (error) {
			console.error("Error fetching role counts:", error);
		}
	}, []);

	const fetchTeams = useCallback(async () => {
		try {
			const response = await api.get<Team[]>("/teams/");
			setTeams(response.data);
		} catch (error) {
			console.error("Error fetching teams:", error);
		}
	}, []);

	useEffect(() => {
		void fetchUsers();
	}, [fetchUsers]);

	useEffect(() => {
		void fetchRoleCounts();
		void fetchTeams();
		const fetchInvites = async () => {
			try {
				const response = await api.get("/invites/");
				setInvites(response.data);
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

	const handleRoleFilterChange = (key: "all" | Role) => {
		setRoleFilter(key);
		setOffset(0);
	};

	const handleCopyInviteLink = async (invite: Invite) => {
		await navigator.clipboard.writeText(invite.inviteUrl);
		setCopiedInviteId(invite.id);
		setTimeout(() => { setCopiedInviteId(null); }, 2000);
	};

	const handleDeleteInvite = async (inviteId: string) => {
		try {
			await api.delete(`/invites/${inviteId}`);
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
			await api.patch(`/users/${userId}/role`, { role: newRole });
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

	const handleTeamChange = async (userId: string, teamId: string | null) => {
		try {
			await api.patch(`/users/${userId}/team`, { teamId });
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

	const handleDeleteTeam = async (team: Team) => {
		const memberCount = team.memberCount;
		const confirmed = window.confirm(
			`Delete "${team.name}"?${
				memberCount > 0
					? ` ${memberCount} member${memberCount === 1 ? "" : "s"} will be unassigned`
					: ""
			} and its agent links will be removed.`,
		);
		if (!confirmed) return;

		try {
			await api.delete(`/teams/${team.id}`);
			setTeams((prev) => prev.filter((t) => t.id !== team.id));
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
		const confirmed = window.confirm(
			`Are you sure you want to remove ${userName || "this user"} from the workspace?`,
		);
		if (!confirmed) return;

		try {
			await api.delete(`/users/${userId}`);
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

	const columns: DataTableColumn<User>[] = [
		{
			key: "name",
			header: "Name",
			width: "minmax(0, 1.4fr)",
			cell: (user) => {
				const isCurrentUser = user.id === currentUser?.id;
				return (
					<div className="flex min-w-0 items-center gap-3">
						<span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-[10.5px] font-bold text-white dark:bg-white/15">
							{getInitials(user.name)}
						</span>
						<div className="min-w-0">
							<div className="flex min-w-0 items-center gap-2">
								<span className="truncate text-[13.5px] font-semibold text-foreground">
									{user.name || "Unnamed"}
								</span>
								{isCurrentUser && (
									<span className="shrink-0 rounded-[4px] bg-petrol-tint px-1.5 py-0.5 font-mono text-[9px] font-bold tracking-[0.06em] text-petrol">
										YOU
									</span>
								)}
							</div>
							{/* Email folds under the name on mobile; own column on md+ */}
							<span className="block truncate font-mono text-[11px] text-meta dark:text-panel-dim md:hidden">
								{user.email}
							</span>
						</div>
					</div>
				);
			},
		},
		{
			key: "email",
			header: "Email",
			width: "230px",
			hideBelowMd: true,
			cell: (user) => (
				<span className="block truncate font-mono text-[11.5px] text-subtle dark:text-muted-foreground">
					{user.email}
				</span>
			),
		},
		{
			key: "role",
			header: "Role",
			width: "130px",
			mobileWidth: "auto",
			cell: (user) => {
				const isCurrentUser = user.id === currentUser?.id;
				return isCurrentUser ? (
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
							{ label: "Admin", onClick: () => { void handleRoleChange(user.id, "admin"); }, active: user.role === "admin" },
							{ label: "Editor", onClick: () => { void handleRoleChange(user.id, "editor"); }, active: user.role === "editor" },
							{ label: "Member", onClick: () => { void handleRoleChange(user.id, "member"); }, active: user.role === "member" },
						]}
					/>
				);
			},
		},
		{
			key: "team",
			header: "Team",
			width: "160px",
			hideBelowMd: true,
			cell: (user) => {
				const team = user.teamId ? teamsById.get(user.teamId) : undefined;
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
							...teams.map((t) => ({
								label: t.name,
								icon: (
									<span
										className="block size-2 rounded-full"
										style={{ background: t.color ?? "#9E9E9E" }}
									/>
								),
								onClick: () => {
									void handleTeamChange(user.id, t.id);
								},
								active: user.teamId === t.id,
							})),
							{ separator: true as const },
							{
								label: "New team",
								icon: <Plus />,
								onClick: () => { handleOpenNewTeam(user.id); },
							},
						]}
					/>
				);
			},
		},
		{
			key: "actions",
			header: "",
			width: "36px",
			cell: (user) => {
				const isCurrentUser = user.id === currentUser?.id;
				return (
					<div className="flex justify-center">
						{!isCurrentUser && (
							<button
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
			intro="Manage who's in your workspace and what they can do."
			search={{
				placeholder: "Search users…",
				value: search,
				onChange: setSearch,
			}}
			actions={
				<WorkspaceTopBarButton
					onClick={() => {
						setInviteDialogOpen(true);
					}}
				>
					<Plus className="size-3.5" />
					Invite user
				</WorkspaceTopBarButton>
			}
		>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<InviteDialog
				open={inviteDialogOpen}
				onOpenChange={setInviteDialogOpen}
				teams={teams}
				onInviteCreated={(invite) => { setInvites((prev) => [...prev, invite]); }}
			/>
			<NewTeamDialog
				open={newTeamDialogOpen}
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
			{/* Role filter chips (design 13c: pills above the table) */}
			<div className="flex flex-wrap items-center gap-2 pb-[18px] pt-1.5">
				{ROLE_FILTERS.map((filter) => {
					const active = roleFilter === filter.key;
					const count =
						filter.key === "all" ? roleCounts?.total : roleCounts?.[filter.key];
					return (
						<button
							key={filter.key}
							type="button"
							onClick={() => {
								handleRoleFilterChange(filter.key);
							}}
							className={
								active
									? "inline-flex cursor-pointer items-center gap-[7px] rounded-full bg-petrol-tint px-[13px] py-1.5 text-[12.5px] font-semibold text-petrol"
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
			</div>

			{/* Member list */}
			<DataTable
				columns={columns}
				rows={users}
				rowKey={(user) => user.id}
				isLoading={isLoading}
				emptyMessage={
					debouncedSearch || roleFilter !== "all"
						? "No users match your filters."
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

			{/* Teams */}
			<div className="flex items-baseline gap-2.5 pt-[18px] pb-3">
				<span className="text-[14px] font-bold tracking-[-0.01em] text-foreground">
					Teams
				</span>
				<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
					{teams.length}
				</span>
				<span className="h-px flex-1 self-center bg-border dark:bg-white/10" />
				<button
					onClick={openCreateTeam}
					className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-border px-3 py-1.5 text-[12px] font-semibold text-subtle transition-colors hover:bg-sidebar dark:border-white/10 dark:text-muted-foreground dark:hover:bg-white/5"
				>
					<Plus className="size-3.5" />
					New team
				</button>
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
							<span className="shrink-0 font-mono text-[10.5px] text-meta dark:text-panel-dim">
								{team.memberCount} member{team.memberCount === 1 ? "" : "s"}
							</span>
							<DropdownMenu
								trigger={
									<button className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-all hover:bg-hover md:opacity-0 md:group-hover:opacity-100 dark:hover:bg-white/10">
										<MoreVertical className="size-[18px]" />
									</button>
								}
								items={[
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
											Invited {timeAgo(invite.createdAt)} · by{" "}
											{getInviterShortName(invite.invitedByName)}
										</div>
									</div>
								</div>

								{/* Status pill */}
								<span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-warning-bg px-2.5 py-1 text-[11px] font-semibold text-warning dark:bg-amber-950 dark:text-amber-300">
									<span className="size-[5px] rounded-full bg-warning" />
									{invite.role in ROLE_LABELS
										? ROLE_LABELS[invite.role as Role]
										: invite.role}{" "}
									invite
								</span>

								{/* Actions */}
								<div className="flex items-center gap-1.5">
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
									<button
										className="cursor-pointer rounded-[7px] border border-border px-3 py-1.5 text-[12px] font-medium text-[#B04A3A] transition-colors hover:bg-[#FBEFED] dark:border-white/10 dark:hover:bg-rose-950"
										onClick={() => { void handleDeleteInvite(invite.id); }}
									>
										Revoke
									</button>
								</div>
							</div>
						))}
					</div>
				</>
			)}
		</WorkspacePage>
	);
}

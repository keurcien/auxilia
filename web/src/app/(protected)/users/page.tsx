"use client";

import { useEffect, useState, useMemo } from "react";
import { Trash2, Plus, Copy, Check, Mail, ChevronDown } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import InviteDialog from "./invite-dialog";
import { SearchBar } from "@/components/ui/search-bar";
import { Button } from "@/components/ui/button";
import { PageContainer } from "@/components/layout/page-container";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { api } from "@/lib/api/client";
import { useUserStore } from "@/stores/user-store";

interface User {
	id: string;
	name: string | null;
	email: string | null;
	role: "member" | "editor" | "admin";
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

type Role = "member" | "editor" | "admin";

const ROLE_LABELS: Record<Role, string> = {
	admin: "Admin",
	editor: "Editor",
	member: "Member",
};

// Only the dot is tinted; the role-control chrome stays neutral.
const ROLE_DOT: Record<Role, string> = {
	admin: "#2f6f4e",
	editor: "#9a7b3c",
	member: "#6f7670",
};

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
	const [invites, setInvites] = useState<Invite[]>([]);
	const [search, setSearch] = useState("");
	const [roleFilter, setRoleFilter] = useState<"all" | Role>("all");
	const [isLoading, setIsLoading] = useState(true);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [inviteDialogOpen, setInviteDialogOpen] = useState(false);
	const [copiedInviteId, setCopiedInviteId] = useState<string | null>(null);

	useEffect(() => {
		const fetchUsers = async () => {
			try {
				const response = await api.get("/users");
				setUsers(response.data);
			} catch (error) {
				console.error("Error fetching users:", error);
			} finally {
				setIsLoading(false);
			}
		};
		const fetchInvites = async () => {
			try {
				const response = await api.get("/invites/");
				setInvites(response.data);
			} catch (error) {
				console.error("Error fetching invites:", error);
			}
		};
		fetchUsers();
		fetchInvites();
	}, []);

	const handleCopyInviteLink = async (invite: Invite) => {
		await navigator.clipboard.writeText(invite.inviteUrl);
		setCopiedInviteId(invite.id);
		setTimeout(() => setCopiedInviteId(null), 2000);
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

	const roleCounts = useMemo(
		() => ({
			all: users.length,
			admin: users.filter((u) => u.role === "admin").length,
			editor: users.filter((u) => u.role === "editor").length,
			member: users.filter((u) => u.role === "member").length,
		}),
		[users],
	);

	const filteredUsers = useMemo(() => {
		let list = users;
		if (roleFilter !== "all") list = list.filter((u) => u.role === roleFilter);
		const query = search.trim().toLowerCase();
		if (query) {
			list = list.filter(
				(user) =>
					user.name?.toLowerCase().includes(query) ||
					user.email?.toLowerCase().includes(query),
			);
		}
		return list;
	}, [users, search, roleFilter]);

	const handleRoleChange = async (userId: string, newRole: Role) => {
		try {
			await api.patch(`/users/${userId}/role`, { role: newRole });
			setUsers((prev) =>
				prev.map((u) => (u.id === userId ? { ...u, role: newRole } : u)),
			);
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

	const handleRemoveUser = async (userId: string, userName: string | null) => {
		const confirmed = window.confirm(
			`Are you sure you want to remove ${userName || "this user"} from the workspace?`,
		);
		if (!confirmed) return;

		try {
			await api.delete(`/users/${userId}`);
			setUsers((prev) => prev.filter((u) => u.id !== userId));
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

	return (
		<PageContainer>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<InviteDialog
				open={inviteDialogOpen}
				onOpenChange={setInviteDialogOpen}
				onInviteCreated={(invite) => setInvites((prev) => [...prev, invite])}
			/>
			<div className="flex flex-col gap-5 my-8 sm:flex-row sm:items-start sm:justify-between">
				<div className="min-w-0">
					<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[32px] tracking-[-0.03em] text-[#111111] dark:text-white">
						Users
					</h1>
					<p className="mt-1.5 font-[family-name:var(--font-dm-sans)] text-[15px] font-medium text-[#6B7F76] dark:text-muted-foreground">
						Manage who&apos;s in your workspace and what they can do.
					</p>
				</div>

				<div className="flex items-center gap-3 shrink-0">
					<SearchBar
						placeholder="Search users..."
						value={search}
						onChange={setSearch}
						hint="⌘K"
						className="w-full sm:w-72"
					/>
					<Button
						className="flex items-center gap-2 px-6! py-3! h-auto! bg-[#111111] dark:bg-white dark:text-[#111111] text-[14px] font-semibold font-[family-name:var(--font-dm-sans)] text-white rounded-full hover:bg-[#222222] dark:hover:bg-gray-100 transition-all cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] border-none whitespace-nowrap"
						onClick={() => setInviteDialogOpen(true)}
					>
						<Plus className="w-4 h-4" />
						Invite user
					</Button>
				</div>
			</div>

			{isLoading ? null : (
				<>
					{/* Role filter chips */}
					<div className="flex flex-wrap items-center gap-2 mb-5">
						{ROLE_FILTERS.map((filter) => {
							const active = roleFilter === filter.key;
							return (
								<button
									key={filter.key}
									onClick={() => setRoleFilter(filter.key)}
									className={`inline-flex items-center gap-2 rounded-full px-[13px] py-1.5 text-[12px] font-[family-name:var(--font-dm-sans)] cursor-pointer transition-colors ${
										active
											? "bg-[#e7f0eb] text-[#3d8b63] font-semibold dark:bg-emerald-950 dark:text-emerald-300"
											: "border border-[#e1ebe6] text-[#5f7068] hover:bg-[#f8faf9] dark:border-white/10 dark:text-muted-foreground dark:hover:bg-white/5"
									}`}
								>
									{filter.label}
									<span className="font-mono text-[10.5px] opacity-70">
										{roleCounts[filter.key]}
									</span>
								</button>
							);
						})}
					</div>

					{/* Member list panel */}
					<div className="overflow-hidden rounded-[14px] border border-[#e1ebe6] bg-white dark:border-white/10 dark:bg-card">
						<div className="grid grid-cols-[1fr_auto_34px] md:grid-cols-[1fr_230px_130px_34px] items-center gap-4 border-b border-[#edf2ef] px-[18px] py-[11px] dark:border-white/5">
							<span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#94a59d]">
								Name
							</span>
							<span className="hidden md:block text-[10px] font-semibold uppercase tracking-[0.1em] text-[#94a59d]">
								Email
							</span>
							<span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-[#94a59d]">
								Role
							</span>
							<span />
						</div>

						{filteredUsers.length === 0 ? (
							<div className="px-[18px] py-12 text-center text-[14px] font-medium text-[#A3B5AD] dark:text-muted-foreground">
								{search || roleFilter !== "all"
									? "No users match your filters."
									: "No members in this workspace."}
							</div>
						) : (
							filteredUsers.map((user) => {
								const isCurrentUser = user.id === currentUser?.id;
								return (
									<div
										key={user.id}
										className="group grid grid-cols-[1fr_auto_34px] md:grid-cols-[1fr_230px_130px_34px] items-center gap-4 border-b border-[#edf2ef] px-[18px] py-[11px] transition-colors duration-[110ms] last:border-b-0 hover:bg-[#eff4f1] dark:border-white/5 dark:hover:bg-white/5"
									>
										{/* Identity */}
										<div className="flex min-w-0 items-center gap-3">
											<span className="flex size-[34px] shrink-0 items-center justify-center rounded-full bg-[#e7f0eb] font-[family-name:var(--font-jakarta-sans)] text-[11.5px] font-bold text-[#3d8b63] dark:bg-emerald-950 dark:text-emerald-300">
												{getInitials(user.name)}
											</span>
											<div className="min-w-0">
												<div className="flex min-w-0 items-center gap-2">
													<span className="truncate font-[family-name:var(--font-jakarta-sans)] text-[13.5px] font-semibold tracking-[-0.01em] text-[#1e2d28] dark:text-foreground">
														{user.name || "Unnamed"}
													</span>
													{isCurrentUser && (
														<span className="shrink-0 rounded-[5px] bg-[#e7f0eb] px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-[0.06em] text-[#3d8b63] dark:bg-emerald-950 dark:text-emerald-300">
															You
														</span>
													)}
												</div>
												{/* Email folds under the name on mobile; own column on md+ */}
												<span className="block truncate font-mono text-[11px] text-[#94a59d] dark:text-muted-foreground md:hidden">
													{user.email}
												</span>
											</div>
										</div>

										{/* Email (column on md+) */}
										<span className="hidden truncate font-mono text-[12px] text-[#5f7068] md:block dark:text-muted-foreground">
											{user.email}
										</span>

										{/* Role */}
										<div className="min-w-0">
											{isCurrentUser ? (
												<span className="inline-flex items-center gap-2 font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#5f7068] dark:text-muted-foreground">
													<span
														className="size-1.5 rounded-full"
														style={{ background: ROLE_DOT[user.role] }}
													/>
													{ROLE_LABELS[user.role]}
												</span>
											) : (
												<SageDropdownMenu
													trigger={
														<button className="inline-flex items-center gap-2 rounded-lg border border-[#e1ebe6] bg-white px-2.5 py-[5px] font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#1e2d28] cursor-pointer transition-colors hover:border-[#A3B5AD] dark:border-white/10 dark:bg-transparent dark:text-foreground">
															<span
																className="size-1.5 rounded-full"
																style={{ background: ROLE_DOT[user.role] }}
															/>
															{ROLE_LABELS[user.role]}
															<ChevronDown className="size-3.5 text-[#94a59d]" />
														</button>
													}
													items={[
														{ label: "Admin", onClick: () => handleRoleChange(user.id, "admin"), active: user.role === "admin" },
														{ label: "Editor", onClick: () => handleRoleChange(user.id, "editor"), active: user.role === "editor" },
														{ label: "Member", onClick: () => handleRoleChange(user.id, "member"), active: user.role === "member" },
													]}
												/>
											)}
										</div>

										{/* Remove */}
										<div className="flex justify-center">
											{!isCurrentUser && (
												<button
													className="flex size-7 items-center justify-center rounded-[7px] text-[#94a59d] opacity-100 transition-all hover:bg-[#fbe5e3] hover:text-[#b03a30] cursor-pointer md:opacity-0 md:group-hover:opacity-100 dark:hover:bg-rose-950"
													onClick={() => handleRemoveUser(user.id, user.name)}
												>
													<Trash2 className="size-[15px]" />
												</button>
											)}
										</div>
									</div>
								);
							})
						)}
					</div>

					{/* Pending invites */}
					{invites.length > 0 && (
						<>
							<div className="flex items-baseline gap-2.5 pt-6 pb-3">
								<span className="font-[family-name:var(--font-jakarta-sans)] text-[14px] font-bold tracking-[-0.01em] text-[#1e2d28] dark:text-foreground">
									Pending invites
								</span>
								<span className="text-[11.5px] text-[#94a59d]">
									{invites.length}
								</span>
								<span className="h-px flex-1 self-center bg-[#e1ebe6] dark:bg-white/10" />
							</div>

							<div className="overflow-hidden rounded-[14px] border border-[#e1ebe6] bg-white dark:border-white/10 dark:bg-card">
								{invites.map((invite) => (
									<div
										key={invite.id}
										className="flex flex-col gap-3 border-b border-[#edf2ef] px-[18px] py-[11px] last:border-b-0 md:grid md:grid-cols-[1fr_140px_auto] md:items-center md:gap-4 dark:border-white/5"
									>
										{/* Envelope + email + meta */}
										<div className="flex min-w-0 items-center gap-3">
											<span className="flex size-[34px] shrink-0 items-center justify-center rounded-full border border-dashed border-[#e1ebe6] bg-surface text-[#94a59d] dark:border-white/10 dark:bg-white/5">
												<Mail className="size-[15px]" />
											</span>
											<div className="min-w-0">
												<div className="truncate font-mono text-[12.5px] font-medium text-[#1e2d28] dark:text-foreground">
													{invite.email}
												</div>
												<div className="truncate text-[11px] text-[#94a59d] mt-0.5">
													Invited {timeAgo(invite.createdAt)} · by{" "}
													{getInviterShortName(invite.invitedByName)}
												</div>
											</div>
										</div>

										{/* Status pill */}
										<span className="inline-flex w-fit items-center gap-1.5 rounded-full bg-[#fbf2da] px-2.5 py-1 text-[11px] font-semibold text-[#9a7b14] dark:bg-amber-950 dark:text-amber-300">
											<span className="size-[5px] rounded-full bg-[#d4a017]" />
											{invite.role in ROLE_LABELS
												? ROLE_LABELS[invite.role as Role]
												: invite.role}{" "}
											invite
										</span>

										{/* Actions */}
										<div className="flex items-center gap-1.5">
											<button
												className="flex items-center gap-1.5 rounded-lg border border-[#e1ebe6] px-3 py-1.5 font-[family-name:var(--font-dm-sans)] text-[12px] font-medium text-[#5f7068] cursor-pointer transition-colors hover:bg-[#f8faf9] dark:border-white/10 dark:text-muted-foreground dark:hover:bg-white/5"
												onClick={() => handleCopyInviteLink(invite)}
											>
												{copiedInviteId === invite.id ? (
													<Check className="size-3.5" />
												) : (
													<Copy className="size-3.5" />
												)}
												{copiedInviteId === invite.id ? "Copied!" : "Copy link"}
											</button>
											<button
												className="rounded-lg border border-[#e1ebe6] px-3 py-1.5 font-[family-name:var(--font-dm-sans)] text-[12px] font-medium text-[#b03a30] cursor-pointer transition-colors hover:bg-[#fbe5e3] dark:border-white/10 dark:hover:bg-rose-950"
												onClick={() => handleDeleteInvite(invite.id)}
											>
												Revoke
											</button>
										</div>
									</div>
								))}
							</div>
						</>
					)}
				</>
			)}
		</PageContainer>
	);
}

"use client";

import { useEffect, useState, useMemo } from "react";
import { Trash2, Plus, Copy, Check, Mail } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import InviteDialog from "./invite-dialog";
import { SearchBar } from "@/components/ui/search-bar";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
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

	const filteredUsers = useMemo(() => {
		if (!search.trim()) return users;
		const query = search.toLowerCase();
		return users.filter(
			(user) =>
				user.name?.toLowerCase().includes(query) ||
				user.email?.toLowerCase().includes(query),
		);
	}, [users, search]);

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
		<div className="mx-auto min-h-full w-full max-w-5xl px-4 pb-20 @min-screen-md/layout:px-8 @min-screen-xl/layout:max-w-6xl">
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
			<div className="flex items-center justify-between my-8 mb-7">
				<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[32px] tracking-[-0.03em] text-[#111111] dark:text-white">
					Users
				</h1>
				<Button
					className="flex items-center gap-2 !px-6 !py-3 !h-auto bg-[#111111] dark:bg-white dark:text-[#111111] text-[14px] font-semibold font-[family-name:var(--font-dm-sans)] text-white rounded-full hover:bg-[#222222] dark:hover:bg-gray-100 transition-all cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] border-none"
					onClick={() => setInviteDialogOpen(true)}
				>
					<Plus className="w-4 h-4" />
					Invite user
				</Button>
			</div>

			{isLoading ? null : (<>
			<SearchBar
				placeholder="Search users..."
				value={search}
				onChange={setSearch}
				className="mb-6 md:max-w-xs w-full"
			/>

			{/* Table header */}
			<div className="flex items-center py-3 pl-[76px] pr-5 mb-1 font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
				<div className="flex-1 text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
					Name
				</div>
				<div className="flex-[1.2] text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
					Email
				</div>
				<div className="min-w-[100px] text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
					Role
				</div>
				<div className="w-[52px]" />
			</div>

			{/* User rows */}
			<div>
				{filteredUsers.length === 0 ? (
					<div className="text-center py-12 text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium">
						{search ? "No users match your search" : "No members in this workspace."}
					</div>
				) : (
					filteredUsers.map((user, i) => {
						const isCurrentUser = user.id === currentUser?.id;

						return (
							<div
								key={user.id}
								className="group flex items-center py-3.5 px-5 rounded-[18px] mb-1 transition-all duration-200 hover:bg-[#F8FAF9] dark:hover:bg-white/5 hover:translate-x-1 animate-in fade-in slide-in-from-bottom-3 duration-400"
								style={{ animationDelay: `${i * 40}ms`, animationFillMode: "both" }}
							>
								{/* Avatar */}
								<div className="shrink-0 w-[42px] h-[42px] rounded-full bg-[#F0F3F2] dark:bg-white/10 border-[1.5px] border-[#E0E8E4] dark:border-white/10 flex items-center justify-center text-[13.5px] font-bold text-[#6B7F76] dark:text-muted-foreground transition-transform duration-300 group-hover:scale-105">
									{getInitials(user.name)}
								</div>

								{/* Name */}
								<div className="flex-1 min-w-0 ml-3.5 font-[family-name:var(--font-dm-sans)]">
									<div className="flex items-center gap-2 text-[14.5px] font-semibold text-[#1E2D28] dark:text-foreground">
										<span className="truncate">{user.name || "Unnamed"}</span>
										{isCurrentUser && (
											<span className="shrink-0 text-[10px] font-bold text-[#8FB5A3] bg-[#EDF4F0] dark:bg-white/10 dark:text-emerald-400 px-2 py-0.5 rounded-full uppercase tracking-[0.04em]">
												You
											</span>
										)}
									</div>
								</div>

								{/* Email */}
								<div className="flex-[1.2] min-w-0 font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#8FA89E] dark:text-muted-foreground font-medium truncate">
									{user.email}
								</div>

								{/* Role */}
								<div className="min-w-[100px]">
									{isCurrentUser ? (
										<span className="font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#6B7F76] dark:text-muted-foreground px-4 py-1.5">
											{ROLE_LABELS[user.role]}
										</span>
									) : (
										<Select
											value={user.role}
											onValueChange={(value: Role) =>
												handleRoleChange(user.id, value)
											}
										>
											<SelectTrigger className="w-[100px] rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent text-[13px] font-semibold font-[family-name:var(--font-dm-sans)] text-[#1E2D28] dark:text-foreground focus:border-[#A3B5AD] h-auto py-1.5">
												<SelectValue />
											</SelectTrigger>
											<SelectContent>
												<SelectItem value="admin">Admin</SelectItem>
												<SelectItem value="editor">Editor</SelectItem>
												<SelectItem value="member">Member</SelectItem>
											</SelectContent>
										</Select>
									)}
								</div>

								{/* Delete */}
								<div className="w-[52px] flex justify-center">
									{!isCurrentUser && (
										<button
											className="w-9 h-9 rounded-xl flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-200 hover:bg-[#F0F3F2] dark:hover:bg-white/10 cursor-pointer"
											onClick={() => handleRemoveUser(user.id, user.name)}
										>
											<Trash2 className="h-[15px] w-[15px] text-[#A3B5AD]" />
										</button>
									)}
								</div>
							</div>
						);
					})
				)}
			</div>

			{invites.length > 0 && (
				<div className="py-10">
					<h2 className="font-[family-name:var(--font-jakarta-sans)] font-bold text-lg tracking-tight text-[#111111] dark:text-white mb-2">
						Pending invites
					</h2>
					<div>
						{invites.map((invite) => (
							<div
								key={invite.id}
								className="group flex items-center py-3.5 px-5 rounded-[18px] mb-1 transition-all duration-200 hover:bg-[#F8FAF9] dark:hover:bg-white/5 hover:translate-x-1"
							>
								{/* Mail icon avatar */}
								<div className="shrink-0 w-[42px] h-[42px] rounded-full bg-[#F0F3F2] dark:bg-white/10 border-[1.5px] border-dashed border-[#E0E8E4] dark:border-white/10 flex items-center justify-center">
									<Mail className="h-4 w-4 text-[#A3B5AD]" />
								</div>

								{/* Email + meta */}
								<div className="flex-1 min-w-0 ml-3.5 font-[family-name:var(--font-dm-sans)]">
									<div className="text-[14.5px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
										{invite.email}
									</div>
									<div className="text-[12px] text-[#B8C8C0] dark:text-muted-foreground font-medium mt-0.5">
										Invited by {getInviterShortName(invite.invitedByName)} · {timeAgo(invite.createdAt)}
									</div>
								</div>

								{/* Role */}
								<span className="shrink-0 font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#6B7F76] dark:text-muted-foreground border-[1.5px] border-[#E0E8E4] dark:border-white/10 rounded-full px-4 py-1.5 text-center min-w-[80px]">
									{ROLE_LABELS[invite.role as Role] ?? invite.role}
								</span>

								{/* Copy link */}
								<button
									className={`shrink-0 flex items-center gap-1.5 ml-2.5 px-4 py-1.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold cursor-pointer transition-all duration-200 ${
										copiedInviteId === invite.id
											? "bg-[#EDF4F0] dark:bg-white/10 text-[#3D8B63] dark:text-emerald-400 border-[#3D8B63]/20"
											: "bg-white dark:bg-transparent text-[#6B7F76] dark:text-muted-foreground hover:border-[#A3B5AD]"
									}`}
									onClick={() => handleCopyInviteLink(invite)}
								>
									{copiedInviteId === invite.id ? (
										<Check className="h-3.5 w-3.5" />
									) : (
										<Copy className="h-3.5 w-3.5" />
									)}
									{copiedInviteId === invite.id ? "Copied!" : "Copy link"}
								</button>

								{/* Delete invite */}
								<button
									className="w-9 h-9 rounded-xl flex items-center justify-center ml-2 opacity-0 group-hover:opacity-100 transition-all duration-200 hover:bg-[#F0F3F2] dark:hover:bg-white/10 cursor-pointer"
									onClick={() => handleDeleteInvite(invite.id)}
								>
									<Trash2 className="h-[15px] w-[15px] text-[#A3B5AD]" />
								</button>
							</div>
						))}
					</div>
				</div>
			)}
			</>)}
		</div>
	);
}

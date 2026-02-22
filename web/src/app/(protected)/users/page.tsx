"use client";

import { useEffect, useState, useMemo } from "react";
import { Search, Trash2, Plus } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import InviteDialog from "./invite-dialog";
import { Input } from "@/components/ui/input";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
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

export default function UsersPage() {
	const currentUser = useUserStore((state) => state.user);
	const [users, setUsers] = useState<User[]>([]);
	const [search, setSearch] = useState("");
	const [isLoading, setIsLoading] = useState(true);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [inviteDialogOpen, setInviteDialogOpen] = useState(false);

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
		fetchUsers();
	}, []);

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
			/>
			<div className="flex items-center justify-between my-8">
				<h1 className="text-3xl font-bold text-foreground">
					Workspace members
				</h1>
				<Button
					className="flex items-center gap-2 px-4 py-2 bg-primary text-sm font-medium text-primary-foreground rounded-lg hover:bg-primary/90 transition-colors cursor-pointer"
					onClick={() => setInviteDialogOpen(true)}
				>
					<Plus className="w-4 h-4" />
					Add member
				</Button>
			</div>

			<div className="relative mb-6">
				<Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
				<Input
					placeholder="Search members..."
					value={search}
					onChange={(e) => setSearch(e.target.value)}
					className="pl-9"
				/>
			</div>

			<div className="rounded-xl border bg-card overflow-hidden">
				<table className="w-full">
					<thead>
						<tr className="border-b bg-muted/50">
							<th className="px-6 py-3 text-left text-sm font-medium text-muted-foreground">
								Name
							</th>
							<th className="px-6 py-3 text-left text-sm font-medium text-muted-foreground">
								Email
							</th>
							<th className="px-6 py-3 text-left text-sm font-medium text-muted-foreground">
								Role
							</th>
							<th className="w-16 px-6 py-3" />
						</tr>
					</thead>
					<tbody>
						{isLoading ? (
							<tr>
								<td
									colSpan={4}
									className="px-6 py-12 text-center text-muted-foreground"
								>
									Loading...
								</td>
							</tr>
						) : filteredUsers.length === 0 ? (
							<tr>
								<td
									colSpan={4}
									className="px-6 py-12 text-center text-muted-foreground"
								>
									{search
										? "No members found."
										: "No members in this workspace."}
								</td>
							</tr>
						) : (
							filteredUsers.map((user) => {
								const isCurrentUser = user.id === currentUser?.id;

								return (
									<tr key={user.id} className="border-b last:border-b-0">
										<td className="px-6 py-4">
											<div className="flex items-center gap-3">
												<Avatar className="h-9 w-9 shrink-0">
													<AvatarFallback className="text-sm">
														{getInitials(user.name)}
													</AvatarFallback>
												</Avatar>
												<span className="text-sm font-medium text-foreground">
													{user.name || "Unnamed"}
												</span>
											</div>
										</td>
										<td className="px-6 py-4">
											<span className="text-sm text-muted-foreground">
												{user.email}
											</span>
										</td>
										<td className="px-6 py-4">
											{isCurrentUser ? (
												<span className="w-28 inline-flex items-center rounded-md border px-3 py-1.5 text-sm text-muted-foreground">
													{ROLE_LABELS[user.role]}
												</span>
											) : (
												<Select
													value={user.role}
													onValueChange={(value: Role) =>
														handleRoleChange(user.id, value)
													}
												>
													<SelectTrigger className="w-28">
														<SelectValue />
													</SelectTrigger>
													<SelectContent>
														<SelectItem value="admin">Admin</SelectItem>
														<SelectItem value="editor">Editor</SelectItem>
														<SelectItem value="member">Member</SelectItem>
													</SelectContent>
												</Select>
											)}
										</td>
										<td className="px-6 py-4">
											{!isCurrentUser && (
												<Button
													variant="ghost"
													size="icon"
													className="h-8 w-8 text-muted-foreground hover:text-destructive cursor-pointer"
													onClick={() => handleRemoveUser(user.id, user.name)}
												>
													<Trash2 className="h-4 w-4" />
												</Button>
											)}
										</td>
									</tr>
								);
							})
						)}
					</tbody>
				</table>
			</div>
		</div>
	);
}

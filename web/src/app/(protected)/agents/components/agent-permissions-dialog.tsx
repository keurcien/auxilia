"use client";

import { useState, useEffect, useMemo } from "react";
import { Search, Trash2 } from "lucide-react";
import { api } from "@/lib/api/client";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";

type PermissionLevel = "user" | "editor" | "admin";

interface User {
	id: string;
	name: string | null;
	email: string | null;
}

interface PermissionRow {
	userId: string;
	permission: PermissionLevel;
}

interface AgentPermissionsDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agentId: string;
	ownerId: string;
}

function getInitials(name: string | null): string {
	if (!name) return "?";
	return name
		.split(" ")
		.map((w) => w[0])
		.join("")
		.slice(0, 2)
		.toUpperCase();
}

export default function AgentPermissionsDialog({
	open,
	onOpenChange,
	agentId,
	ownerId,
}: AgentPermissionsDialogProps) {
	const [allUsers, setAllUsers] = useState<User[]>([]);
	const [permissions, setPermissions] = useState<PermissionRow[]>([]);
	const [search, setSearch] = useState("");
	const [isSaving, setIsSaving] = useState(false);
	const [isLoading, setIsLoading] = useState(false);

	useEffect(() => {
		if (!open) return;

		setIsLoading(true);
		setSearch("");
		Promise.all([api.get("/users"), api.get(`/agents/${agentId}/permissions`)])
			.then(([usersRes, permsRes]) => {
				setAllUsers(usersRes.data);
				setPermissions(
					(permsRes.data as PermissionRow[]).map((p) => ({
						userId: p.userId,
						permission: p.permission,
					})),
				);
			})
			.catch((err) => console.error("Failed to load permissions:", err))
			.finally(() => setIsLoading(false));
	}, [open, agentId]);

	const owner = useMemo(
		() => allUsers.find((u) => u.id === ownerId) ?? null,
		[allUsers, ownerId],
	);

	const permittedUsers = useMemo(() => {
		return permissions
			.map((p) => {
				const user = allUsers.find((u) => u.id === p.userId);
				return user ? { ...user, permission: p.permission } : null;
			})
			.filter(Boolean) as (User & { permission: PermissionLevel })[];
	}, [permissions, allUsers]);

	const searchResults = useMemo(() => {
		if (!search.trim()) return [];
		const q = search.toLowerCase();
		const permittedIds = new Set(permissions.map((p) => p.userId));
		return allUsers.filter(
			(u) =>
				u.id !== ownerId &&
				!permittedIds.has(u.id) &&
				((u.name && u.name.toLowerCase().includes(q)) ||
					(u.email && u.email.toLowerCase().includes(q))),
		);
	}, [search, allUsers, permissions, ownerId]);

	const addUser = (userId: string) => {
		setPermissions((prev) => [...prev, { userId, permission: "user" }]);
		setSearch("");
	};

	const removeUser = (userId: string) => {
		setPermissions((prev) => prev.filter((p) => p.userId !== userId));
	};

	const updatePermission = (userId: string, permission: PermissionLevel) => {
		setPermissions((prev) =>
			prev.map((p) => (p.userId === userId ? { ...p, permission } : p)),
		);
	};

	const handleSave = async () => {
		setIsSaving(true);
		try {
			await api.put(`/agents/${agentId}/permissions`, permissions);
			onOpenChange(false);
		} catch (err) {
			console.error("Failed to save permissions:", err);
		} finally {
			setIsSaving(false);
		}
	};

	const handleCancel = () => {
		onOpenChange(false);
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent
				className="sm:max-w-[640px] h-[480px] flex flex-col"
				showCloseButton={false}
			>
				<DialogHeader>
					<DialogTitle>Manage permissions</DialogTitle>
				</DialogHeader>

				<div className="relative">
					<Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-muted-foreground" />
					<Input
						placeholder="Search users by name or email..."
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						className="pl-9"
					/>
				</div>

				{search.trim() && searchResults.length > 0 && (
					<div className="border rounded-md max-h-[140px] overflow-y-auto shrink-0">
						{searchResults.map((user) => (
							<button
								key={user.id}
								type="button"
								className="w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-accent transition-colors cursor-pointer"
								onClick={() => addUser(user.id)}
							>
								<div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
									{getInitials(user.name)}
								</div>
								<div className="flex-1 min-w-0">
									<p className="text-sm font-medium truncate">
										{user.name || "Unnamed"}
									</p>
									<p className="text-xs text-muted-foreground truncate">
										{user.email}
									</p>
								</div>
							</button>
						))}
					</div>
				)}

				{search.trim() && searchResults.length === 0 && !isLoading && (
					<p className="text-sm text-muted-foreground text-center py-2">
						No users found.
					</p>
				)}

				<div className="flex-1 min-h-0 overflow-hidden border rounded-md">
					<div className="h-full overflow-y-auto">
						<table className="w-full">
							<thead className="sticky top-0 bg-muted/50 backdrop-blur-sm">
								<tr className="text-left text-xs text-muted-foreground font-medium">
									<th className="px-3 py-2">Name</th>
									<th className="px-3 py-2">Email</th>
									<th className="px-3 py-2 w-[130px]">Role</th>
									<th className="px-3 py-2 w-[50px]" />
								</tr>
							</thead>
							<tbody className="text-sm">
								{owner && (
									<tr className="border-t">
										<td className="px-3 py-2">
											<div className="flex items-center gap-2">
												<div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
													{getInitials(owner.name)}
												</div>
												<span className="truncate max-w-[120px]">
													{owner.name || "Unnamed"}
												</span>
											</div>
										</td>
										<td className="px-3 py-2 text-muted-foreground truncate max-w-[160px]">
											{owner.email}
										</td>
										<td className="px-3 py-2">
											<div className="flex h-8 w-full items-center rounded-md border bg-transparent px-3 text-sm text-muted-foreground">
												Owner
											</div>
										</td>
										<td className="px-3 py-2" />
									</tr>
								)}
								{permittedUsers.map((user) => (
									<tr key={user.id} className="border-t">
										<td className="px-3 py-2">
											<div className="flex items-center gap-2">
												<div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted text-xs font-medium">
													{getInitials(user.name)}
												</div>
												<span className="truncate max-w-[120px]">
													{user.name || "Unnamed"}
												</span>
											</div>
										</td>
										<td className="px-3 py-2 text-muted-foreground truncate max-w-[160px]">
											{user.email}
										</td>
										<td className="px-3 py-2">
											<Select
												value={user.permission}
												onValueChange={(value) =>
													updatePermission(user.id, value as PermissionLevel)
												}
											>
												<SelectTrigger size="sm" className="w-full">
													<SelectValue />
												</SelectTrigger>
												<SelectContent>
													<SelectItem value="user">User</SelectItem>
													<SelectItem value="editor">Editor</SelectItem>
													<SelectItem value="admin">Admin</SelectItem>
												</SelectContent>
											</Select>
										</td>
										<td className="px-3 py-2">
											<Button
												variant="ghost"
												size="icon-sm"
												className="cursor-pointer text-muted-foreground hover:text-destructive"
												onClick={() => removeUser(user.id)}
											>
												<Trash2 className="size-4" />
											</Button>
										</td>
									</tr>
								))}
								{!owner && permittedUsers.length === 0 && !isLoading && (
									<tr>
										<td
											colSpan={4}
											className="px-3 py-8 text-center text-sm text-muted-foreground"
										>
											No permissions set. Search for users to add.
										</td>
									</tr>
								)}
							</tbody>
						</table>
					</div>
				</div>

				<DialogFooter className="shrink-0">
					<Button
						variant="outline"
						onClick={handleCancel}
						className="cursor-pointer"
					>
						Cancel
					</Button>
					<Button
						onClick={handleSave}
						disabled={isSaving}
						className="cursor-pointer"
					>
						{isSaving ? "Saving..." : "Save"}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

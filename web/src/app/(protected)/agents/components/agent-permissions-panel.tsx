"use client";

import { useState, useEffect, useMemo } from "react";
import { Trash2, ChevronDown } from "lucide-react";
import * as agentsApi from "@/lib/api/resources/agents";
import * as usersApi from "@/lib/api/resources/users";
import { SearchBar } from "@/components/ui/search-bar";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { UserAvatar } from "@/components/ui/user-avatar";
import type { User as WorkspaceUser } from "@/types/users";

type PermissionLevel = agentsApi.GrantLevel;
type PermissionRow = agentsApi.AgentPermissionRow;

type User = Pick<
	WorkspaceUser,
	"id" | "name" | "email" | "pictureUrl" | "imageRevision"
>;

interface AgentPermissionsPanelProps {
	agentId: string;
	ownerId: string;
}

const PERMISSION_LABELS: Record<PermissionLevel, string> = {
	admin: "Admin",
	editor: "Editor",
	member: "Member",
};

/**
 * The Permissions editor tab: explicit user grants for this agent. Team access
 * is the agent's visibility scope and is edited with the main config.
 * Saves through its own PUT (permissions are not part of the config draft),
 * so the panel keeps an explicit save button with its own dirty state.
 */
export default function AgentPermissionsPanel({
	agentId,
	ownerId,
}: AgentPermissionsPanelProps) {
	const [allUsers, setAllUsers] = useState<User[]>([]);
	const [permissions, setPermissions] = useState<PermissionRow[]>([]);
	const [savedSnapshot, setSavedSnapshot] = useState<string>("");
	const [search, setSearch] = useState("");
	const [isSaving, setIsSaving] = useState(false);
	const [isLoading, setIsLoading] = useState(false);

	const snapshotOf = (perms: PermissionRow[]) =>
		JSON.stringify([...perms].sort((a, b) => a.userId.localeCompare(b.userId)));

	useEffect(() => {
		setIsLoading(true);
		setSearch("");
		Promise.all([
			// The picker needs the whole workspace; 200 is the API's max page size.
			usersApi.listUsers({ limit: 200, offset: 0 }),
			agentsApi.listAgentPermissions(agentId),
		])
			.then(([usersPage, permissionRows]) => {
				setAllUsers(usersPage.items);
				const perms = permissionRows.map((p) => ({
					userId: p.userId,
					permission: p.permission,
				}));
				setPermissions(perms);
				setSavedSnapshot(snapshotOf(perms));
			})
			.catch((err) => { console.error("Failed to load permissions:", err); })
			.finally(() => { setIsLoading(false); });
	}, [agentId]);

	const isDirty =
		savedSnapshot !== "" &&
		snapshotOf(permissions) !== savedSnapshot;

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
		setPermissions((prev) => [...prev, { userId, permission: "member" }]);
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
			await agentsApi.setAgentPermissions(agentId, permissions);
			setSavedSnapshot(snapshotOf(permissions));
		} catch (err) {
			console.error("Failed to save permissions:", err);
		} finally {
			setIsSaving(false);
		}
	};

	return (
		<div className="flex flex-col gap-4">
			<div className="flex items-center justify-end gap-4">
				{isDirty && (
					<button
						type="button"
						disabled={isSaving}
						onClick={() => {
							void handleSave();
						}}
						className="shrink-0 cursor-pointer rounded-[7px] bg-petrol px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
					>
						{isSaving ? "Saving…" : "Save permissions"}
					</button>
				)}
			</div>

			<>
					<div className="relative">
						<SearchBar
							placeholder="Search users by name or email…"
							value={search}
							onChange={setSearch}
						/>

						{search.trim() && searchResults.length > 0 && (
							<div className="absolute left-0 right-0 top-full z-10 mt-2 max-h-[200px] overflow-y-auto rounded-[10px] border border-border bg-popover shadow-composer [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
								{searchResults.map((user) => (
									<button
										key={user.id}
										type="button"
										className="flex w-full cursor-pointer items-center gap-3 border-b border-hover px-4 py-2.5 text-left transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5"
										onClick={() => { addUser(user.id); }}
									>
										<UserAvatar
											name={user.name}
											pictureUrl={user.pictureUrl}
											userId={user.id}
											imageRevision={user.imageRevision}
											className="size-7 shrink-0"
											fallbackClassName="bg-primary text-[10px] text-primary-foreground dark:bg-primary"
										/>
										<span className="min-w-0 flex-1">
											<span className="block truncate text-[13.5px] font-semibold text-foreground">
												{user.name || "Unnamed"}
											</span>
											<span className="block truncate font-mono text-[11px] text-meta dark:text-panel-dim">
												{user.email}
											</span>
										</span>
									</button>
								))}
							</div>
						)}

						{search.trim() && searchResults.length === 0 && !isLoading && (
							<div className="absolute left-0 right-0 top-full z-10 mt-2 rounded-[10px] border border-border bg-popover py-4 text-center text-[13px] text-meta shadow-composer dark:text-panel-dim">
								No users found.
							</div>
						)}
					</div>

					<div className="overflow-hidden rounded-[10px] border border-border bg-card">
						{owner && (
							<div className="flex items-center gap-3 border-b border-hover px-4 py-3 last:border-b-0 dark:border-white/5">
								<UserAvatar
									name={owner.name}
									pictureUrl={owner.pictureUrl}
									userId={owner.id}
									imageRevision={owner.imageRevision}
									className="size-7 shrink-0"
									fallbackClassName="bg-primary text-[10px] text-primary-foreground dark:bg-primary"
								/>
								<span className="min-w-0 flex-1">
									<span className="block truncate text-[13.5px] font-semibold text-foreground">
										{owner.name || "Unnamed"}
									</span>
									<span className="block truncate font-mono text-[11px] text-meta dark:text-panel-dim">
										{owner.email}
									</span>
								</span>
								<span className="rounded-[4px] bg-success-bg px-2 py-0.5 text-[9.5px] font-semibold text-success">
									Owner
								</span>
							</div>
						)}

						{permittedUsers.map((user) => (
							<div
								key={user.id}
								className="group flex items-center gap-3 border-b border-hover px-4 py-2.5 last:border-b-0 dark:border-white/5"
							>
								<UserAvatar
									name={user.name}
									pictureUrl={user.pictureUrl}
									userId={user.id}
									imageRevision={user.imageRevision}
									className="size-7 shrink-0"
									fallbackClassName="bg-primary text-[10px] text-primary-foreground dark:bg-primary"
								/>
								<span className="min-w-0 flex-1">
									<span className="block truncate text-[13.5px] font-semibold text-foreground">
										{user.name || "Unnamed"}
									</span>
									<span className="block truncate font-mono text-[11px] text-meta dark:text-panel-dim">
										{user.email}
									</span>
								</span>
								<DropdownMenu
									trigger={
										<button className="flex w-[96px] cursor-pointer items-center justify-between gap-1 rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover">
											<span>{PERMISSION_LABELS[user.permission]}</span>
											<ChevronDown className="size-3.5 shrink-0 text-meta" />
										</button>
									}
									items={[
										{ label: "Admin", onClick: () => { updatePermission(user.id, "admin"); }, active: user.permission === "admin" },
										{ label: "Editor", onClick: () => { updatePermission(user.id, "editor"); }, active: user.permission === "editor" },
										{ label: "Member", onClick: () => { updatePermission(user.id, "member"); }, active: user.permission === "member" },
									]}
								/>
								<button
									aria-label={`Remove ${user.name ?? "user"}`}
									className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-[7px] text-meta transition-all hover:bg-hover hover:text-foreground md:opacity-0 md:group-hover:opacity-100 dark:text-panel-dim dark:hover:bg-white/10"
									onClick={() => { removeUser(user.id); }}
								>
									<Trash2 className="size-3.5" />
								</button>
							</div>
						))}

						{!owner && permittedUsers.length === 0 && !isLoading && (
							<div className="px-4 py-10 text-center text-[13px] text-meta dark:text-panel-dim">
								No permissions set. Search for users to add.
							</div>
						)}
					</div>
			</>
		</div>
	);
}

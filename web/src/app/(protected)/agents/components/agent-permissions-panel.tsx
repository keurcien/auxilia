"use client";

import { useState, useEffect, useMemo } from "react";
import { Trash2, ChevronDown, Check, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import { SearchBar } from "@/components/ui/search-bar";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { UnderlineTabs } from "@/components/ui/underline-tabs";

type PermissionLevel = "member" | "editor" | "admin";

interface User {
	id: string;
	name: string | null;
	email: string | null;
}

interface Team {
	id: string;
	name: string;
	color: string | null;
}

interface PermissionRow {
	userId: string;
	permission: PermissionLevel;
}

interface AgentPermissionsPanelProps {
	agentId: string;
	ownerId: string;
}

const PERMISSION_LABELS: Record<PermissionLevel, string> = {
	admin: "Admin",
	editor: "Editor",
	member: "Member",
};

function getInitials(name: string | null): string {
	if (!name) return "?";
	return name
		.split(" ")
		.map((w) => w[0])
		.join("")
		.slice(0, 2)
		.toUpperCase();
}

/**
 * The Permissions editor tab: who can use/edit this agent, plus team grants.
 * Saves through its own PUTs (permissions are not part of the config draft),
 * so the panel keeps an explicit save button with its own dirty state.
 */
export default function AgentPermissionsPanel({
	agentId,
	ownerId,
}: AgentPermissionsPanelProps) {
	const [allUsers, setAllUsers] = useState<User[]>([]);
	const [permissions, setPermissions] = useState<PermissionRow[]>([]);
	const [allTeams, setAllTeams] = useState<Team[]>([]);
	const [selectedTeamIds, setSelectedTeamIds] = useState<string[]>([]);
	const [savedSnapshot, setSavedSnapshot] = useState<string>("");
	const [view, setView] = useState<"people" | "teams">("people");
	const [search, setSearch] = useState("");
	const [isSaving, setIsSaving] = useState(false);
	const [isLoading, setIsLoading] = useState(false);

	const snapshotOf = (perms: PermissionRow[], teamIds: string[]) =>
		JSON.stringify({
			perms: [...perms].sort((a, b) => a.userId.localeCompare(b.userId)),
			teams: [...teamIds].sort(),
		});

	useEffect(() => {
		setIsLoading(true);
		setSearch("");
		Promise.all([
			// The picker needs the whole workspace; 200 is the API's max page size.
			api.get("/users", { params: { limit: 200 } }),
			api.get(`/agents/${agentId}/permissions`),
			api.get("/teams/"),
			api.get(`/agents/${agentId}/teams`),
		])
			.then(([usersRes, permsRes, teamsRes, agentTeamsRes]) => {
				setAllUsers((usersRes.data as { items: User[] }).items);
				const perms = (permsRes.data as PermissionRow[]).map((p) => ({
					userId: p.userId,
					permission: p.permission,
				}));
				const teamIds = (agentTeamsRes.data as { teamIds: string[] }).teamIds;
				setPermissions(perms);
				setAllTeams(teamsRes.data);
				setSelectedTeamIds(teamIds);
				setSavedSnapshot(snapshotOf(perms, teamIds));
			})
			.catch((err) => { console.error("Failed to load permissions:", err); })
			.finally(() => { setIsLoading(false); });
	}, [agentId]);

	const isDirty =
		savedSnapshot !== "" &&
		snapshotOf(permissions, selectedTeamIds) !== savedSnapshot;

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

	const toggleTeam = (teamId: string) => {
		setSelectedTeamIds((prev) =>
			prev.includes(teamId)
				? prev.filter((id) => id !== teamId)
				: [...prev, teamId],
		);
	};

	const handleSave = async () => {
		setIsSaving(true);
		try {
			await Promise.all([
				api.put(`/agents/${agentId}/permissions`, permissions),
				api.put(`/agents/${agentId}/teams`, { teamIds: selectedTeamIds }),
			]);
			setSavedSnapshot(snapshotOf(permissions, selectedTeamIds));
		} catch (err) {
			console.error("Failed to save permissions:", err);
		} finally {
			setIsSaving(false);
		}
	};

	return (
		<div className="flex flex-col gap-4">
			<div className="flex items-center justify-between gap-4">
				<UnderlineTabs
					tabs={[
						{ key: "people", label: "People" },
						{ key: "teams", label: "Teams" },
					]}
					value={view}
					onChange={setView}
				/>
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

			{view === "people" ? (
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
										<span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
											{getInitials(user.name)}
										</span>
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
								<span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
									{getInitials(owner.name)}
								</span>
								<span className="min-w-0 flex-1">
									<span className="block truncate text-[13.5px] font-semibold text-foreground">
										{owner.name || "Unnamed"}
									</span>
									<span className="block truncate font-mono text-[11px] text-meta dark:text-panel-dim">
										{owner.email}
									</span>
								</span>
								<span className="rounded-[4px] bg-success-bg px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em] text-success">
									OWNER
								</span>
							</div>
						)}

						{permittedUsers.map((user) => (
							<div
								key={user.id}
								className="group flex items-center gap-3 border-b border-hover px-4 py-2.5 last:border-b-0 dark:border-white/5"
							>
								<span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-[10px] font-bold text-primary-foreground">
									{getInitials(user.name)}
								</span>
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
			) : (
				<div className="flex flex-col gap-3">
					<p className="text-[13px] text-muted-foreground">
						Select teams to grant their members{" "}
						<span className="font-semibold text-foreground">Member</span>{" "}
						access to this agent.
					</p>

					{allTeams.length === 0 ? (
						<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
							No teams yet. Create one from the Users page.
						</div>
					) : (
						<div className="flex flex-wrap gap-2">
							{allTeams.map((team) => {
								const selected = selectedTeamIds.includes(team.id);
								return (
									<button
										key={team.id}
										type="button"
										onClick={() => {
											toggleTeam(team.id);
										}}
										className={cn(
											"inline-flex cursor-pointer items-center gap-2 rounded-full border px-3.5 py-2 text-[13px] font-semibold transition-colors",
											selected
												? "border-petrol bg-petrol-tint text-foreground"
												: "border-dashed border-input text-muted-foreground hover:border-border-hover hover:bg-sidebar dark:hover:bg-white/5",
										)}
									>
										<span
											className="size-2 shrink-0 rounded-full"
											style={{ background: team.color ?? "#9E9E9E" }}
										/>
										{team.name}
										{selected ? (
											<Check className="size-3.5 shrink-0 text-petrol" />
										) : (
											<Plus className="size-3.5 shrink-0 text-meta" />
										)}
									</button>
								);
							})}
						</div>
					)}
				</div>
			)}
		</div>
	);
}

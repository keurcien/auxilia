"use client";

import { useState, useEffect, useMemo } from "react";
import { Trash2, ChevronDown, Check, Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { cn } from "@/lib/utils";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogFooter,
} from "@/components/ui/dialog";
import { SearchBar } from "@/components/ui/search-bar";
import { SageButton } from "@/components/ui/sage-button";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";

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

interface AgentPermissionsDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
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

export default function AgentPermissionsDialog({
	open,
	onOpenChange,
	agentId,
	ownerId,
}: AgentPermissionsDialogProps) {
	const [allUsers, setAllUsers] = useState<User[]>([]);
	const [permissions, setPermissions] = useState<PermissionRow[]>([]);
	const [allTeams, setAllTeams] = useState<Team[]>([]);
	const [selectedTeamIds, setSelectedTeamIds] = useState<string[]>([]);
	const [view, setView] = useState<"people" | "teams">("people");
	const [search, setSearch] = useState("");
	const [isSaving, setIsSaving] = useState(false);
	const [isLoading, setIsLoading] = useState(false);

	useEffect(() => {
		if (!open) return;

		setIsLoading(true);
		setSearch("");
		setView("people");
		// Clear prior agent's data so stale teams/permissions can't linger or be
		// saved if this load is slow or fails.
		setPermissions([]);
		setAllTeams([]);
		setSelectedTeamIds([]);
		Promise.all([
			// The picker needs the whole workspace; 200 is the API's max page size.
			api.get("/users", { params: { limit: 200 } }),
			api.get(`/agents/${agentId}/permissions`),
			api.get("/teams/"),
			api.get(`/agents/${agentId}/teams`),
		])
			.then(([usersRes, permsRes, teamsRes, agentTeamsRes]) => {
				setAllUsers((usersRes.data as { items: User[] }).items);
				setPermissions(
					(permsRes.data as PermissionRow[]).map((p) => ({
						userId: p.userId,
						permission: p.permission,
					})),
				);
				setAllTeams(teamsRes.data);
				setSelectedTeamIds(
					(agentTeamsRes.data as { teamIds: string[] }).teamIds,
				);
			})
			.catch((err) => { console.error("Failed to load permissions:", err); })
			.finally(() => { setIsLoading(false); });
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

				{/* People / Teams toggle */}
				<div className="flex shrink-0 w-fit gap-1 rounded-full bg-[#F0F3F2] dark:bg-white/5 p-1">
					{(["people", "teams"] as const).map((tab) => (
						<button
							key={tab}
							type="button"
							onClick={() => {
								setView(tab);
							}}
							className={cn(
								"rounded-full px-4 py-1.5 text-[13px] font-semibold font-[family-name:var(--font-dm-sans)] cursor-pointer transition-colors",
								view === tab
									? "bg-white dark:bg-white/10 text-[#1E2D28] dark:text-foreground shadow-[0_1px_3px_rgba(0,0,0,0.06)]"
									: "text-[#8FA89E] hover:text-[#6B7F76]",
							)}
						>
							{tab === "people" ? "People" : "Teams"}
						</button>
					))}
				</div>

				{view === "people" ? (
					<>
						<div className="relative">
							<SearchBar
								placeholder="Search users by name or email..."
								value={search}
								onChange={setSearch}
							/>

							{search.trim() && searchResults.length > 0 && (
								<div className="absolute top-full left-0 right-0 mt-2 z-10 bg-white dark:bg-[#1C1C1C] border-[1.5px] border-[#E0E8E4] dark:border-white/10 rounded-[18px] max-h-[160px] overflow-y-auto shadow-[0_8px_24px_-6px_rgba(0,0,0,0.08)] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
									{searchResults.map((user) => (
										<button
											key={user.id}
											type="button"
											className="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-[#F8FAF9] dark:hover:bg-white/5 transition-colors cursor-pointer first:rounded-t-[16px] last:rounded-b-[16px]"
											onClick={() => { addUser(user.id); }}
										>
											<div className="shrink-0 w-[34px] h-[34px] rounded-full bg-[#F0F3F2] dark:bg-white/10 border-[1.5px] border-[#E0E8E4] dark:border-white/10 flex items-center justify-center text-[12px] font-bold text-[#6B7F76] dark:text-muted-foreground">
												{getInitials(user.name)}
											</div>
											<div className="flex-1 min-w-0">
												<p className="font-[family-name:var(--font-dm-sans)] text-[13.5px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
													{user.name || "Unnamed"}
												</p>
												<p className="font-[family-name:var(--font-dm-sans)] text-[12px] text-[#8FA89E] dark:text-muted-foreground truncate">
													{user.email}
												</p>
											</div>
										</button>
									))}
								</div>
							)}

							{search.trim() && searchResults.length === 0 && !isLoading && (
								<div className="absolute top-full left-0 right-0 mt-2 z-10 bg-white dark:bg-[#1C1C1C] border-[1.5px] border-[#E0E8E4] dark:border-white/10 rounded-[18px] shadow-[0_8px_24px_-6px_rgba(0,0,0,0.08)]">
									<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#A3B5AD] dark:text-muted-foreground text-center py-4">
										No users found.
									</p>
								</div>
							)}
						</div>

						<div className="flex flex-1 flex-col min-h-0">
							{/* Table header */}
							<div className="flex shrink-0 items-center py-2 px-5 pl-[66px] font-[family-name:var(--font-dm-sans)]">
								<div className="flex-1 text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
									Name
								</div>
								<div className="flex-[1.2] text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
									Email
								</div>
								<div className="min-w-[100px] text-[11px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
									Role
								</div>
								<div className="w-[40px]" />
							</div>

							{/* Rows */}
							<div className="min-h-0 flex-1 overflow-y-auto pb-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
								{owner && (
									<div className="flex items-center py-3 px-5 rounded-[16px] transition-all duration-200 hover:bg-[#F8FAF9] dark:hover:bg-white/5">
										<div className="shrink-0 w-[34px] h-[34px] rounded-full bg-[#F0F3F2] dark:bg-white/10 border-[1.5px] border-[#E0E8E4] dark:border-white/10 flex items-center justify-center text-[12px] font-bold text-[#6B7F76] dark:text-muted-foreground">
											{getInitials(owner.name)}
										</div>
										<div className="flex-1 min-w-0 ml-3 font-[family-name:var(--font-dm-sans)]">
											<span className="text-[13.5px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
												{owner.name || "Unnamed"}
											</span>
										</div>
										<div className="flex-[1.2] min-w-0 font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground font-medium truncate">
											{owner.email}
										</div>
										<div className="min-w-[100px]">
											<span className="font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold text-[#6B7F76] dark:text-muted-foreground px-4 py-1.5">
												Owner
											</span>
										</div>
										<div className="w-[40px]" />
									</div>
								)}

								{permittedUsers.map((user) => (
									<div
										key={user.id}
										className="group flex items-center py-3 px-5 rounded-[16px] transition-all duration-200 hover:bg-[#F8FAF9] dark:hover:bg-white/5"
									>
										<div className="shrink-0 w-[34px] h-[34px] rounded-full bg-[#F0F3F2] dark:bg-white/10 border-[1.5px] border-[#E0E8E4] dark:border-white/10 flex items-center justify-center text-[12px] font-bold text-[#6B7F76] dark:text-muted-foreground">
											{getInitials(user.name)}
										</div>
										<div className="flex-1 min-w-0 ml-3 font-[family-name:var(--font-dm-sans)]">
											<span className="text-[13.5px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
												{user.name || "Unnamed"}
											</span>
										</div>
										<div className="flex-[1.2] min-w-0 font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground font-medium truncate">
											{user.email}
										</div>
										<div className="min-w-[100px]">
											<SageDropdownMenu
												trigger={
													<button className="w-[100px] rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent text-[13px] font-semibold font-[family-name:var(--font-dm-sans)] text-[#1E2D28] dark:text-foreground h-auto py-1.5 px-4 flex items-center justify-between gap-1 cursor-pointer hover:border-[#A3B5AD] transition-colors">
														<span>{PERMISSION_LABELS[user.permission]}</span>
														<ChevronDown className="size-3.5 text-[#8FA89E] shrink-0" />
													</button>
												}
												items={[
													{ label: "Admin", onClick: () => { updatePermission(user.id, "admin"); }, active: user.permission === "admin" },
													{ label: "Editor", onClick: () => { updatePermission(user.id, "editor"); }, active: user.permission === "editor" },
													{ label: "Member", onClick: () => { updatePermission(user.id, "member"); }, active: user.permission === "member" },
												]}
											/>
										</div>
										<div className="w-[40px] flex justify-center">
											<button
												className="w-8 h-8 rounded-xl flex items-center justify-center opacity-0 group-hover:opacity-100 transition-all duration-200 hover:bg-[#F0F3F2] dark:hover:bg-white/10 cursor-pointer"
												onClick={() => { removeUser(user.id); }}
											>
												<Trash2 className="h-[15px] w-[15px] text-[#A3B5AD]" />
											</button>
										</div>
									</div>
								))}

								{!owner && permittedUsers.length === 0 && !isLoading && (
									<div className="text-center py-12 font-[family-name:var(--font-dm-sans)] text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium">
										No permissions set. Search for users to add.
									</div>
								)}
							</div>
						</div>
					</>
				) : (
					<div className="flex flex-1 flex-col min-h-0">
						<p className="shrink-0 px-1 pb-3 font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground">
							Select teams to grant their members{" "}
							<span className="font-semibold text-[#6B7F76] dark:text-foreground">
								Member
							</span>{" "}
							access to this agent.
						</p>

						<div className="min-h-0 flex-1 overflow-y-auto pb-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							{allTeams.length === 0 ? (
								<div className="text-center py-12 font-[family-name:var(--font-dm-sans)] text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium">
									No teams yet. Create one from the Users page.
								</div>
							) : (
								<div className="flex flex-wrap gap-2 px-1">
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
													"inline-flex items-center gap-2 rounded-full border-[1.5px] px-3.5 py-2 text-[13px] font-semibold font-[family-name:var(--font-dm-sans)] cursor-pointer transition-colors",
													selected
														? "border-[#4CA882] bg-[#EDF4F0] dark:bg-emerald-950/40 text-[#1E2D28] dark:text-foreground"
														: "border-dashed border-[#CBD8D2] dark:border-white/15 text-[#6B7F76] dark:text-muted-foreground hover:border-[#A3B5AD] hover:bg-[#F8FAF9] dark:hover:bg-white/5",
												)}
											>
												<span
													className="size-2 shrink-0 rounded-full"
													style={{ background: team.color ?? "#9E9E9E" }}
												/>
												{team.name}
												{selected ? (
													<Check className="size-3.5 shrink-0 text-[#4CA882]" />
												) : (
													<Plus className="size-3.5 shrink-0 text-[#8FA89E]" />
												)}
											</button>
										);
									})}
								</div>
							)}
						</div>
					</div>
				)}

				<DialogFooter className="shrink-0">
					<SageButton color="outline" onClick={handleCancel}>
						Cancel
					</SageButton>
					<SageButton onClick={() => { void handleSave(); }} disabled={isSaving}>
						{isSaving ? "Saving..." : "Save"}
					</SageButton>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}

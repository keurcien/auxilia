"use client";

import { useEffect, useMemo, useState } from "react";
import { Copy, Check } from "lucide-react";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import * as invitesApi from "@/lib/api/resources/invites";
import * as teamsApi from "@/lib/api/resources/teams";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useWorkspacesStore } from "@/stores/workspaces-store";
import type { Invite, Team, WorkspaceRole as Role } from "@/types/users";

const fieldClass =
	"w-full rounded-lg border border-input bg-card px-3 py-[9px] text-[13.5px] font-medium text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)]";
const selectClass = `${fieldClass} cursor-pointer appearance-none pr-9 bg-[url('data:image/svg+xml,%3Csvg%20width%3D%2712%27%20height%3D%2712%27%20viewBox%3D%270%200%2024%2024%27%20fill%3D%27none%27%20stroke%3D%27%238FA89E%27%20stroke-width%3D%272%27%20stroke-linecap%3D%27round%27%20stroke-linejoin%3D%27round%27%20xmlns%3D%27http%3A//www.w3.org/2000/svg%27%3E%3Cpolyline%20points%3D%276%209%2012%2015%2018%209%27/%3E%3C/svg%3E')] bg-no-repeat bg-[right_12px_center]`;
const labelClass = "text-[13px] font-semibold text-ink dark:text-panel-button";

interface InviteDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	onInviteCreated?: (invite: Invite) => void;
}

export default function InviteDialog({
	open,
	onOpenChange,
	onInviteCreated,
}: InviteDialogProps) {
	const workspaces = useWorkspacesStore((state) => state.workspaces);
	const activeWorkspaceId = useWorkspacesStore((state) => state.activeWorkspaceId);
	const adminWorkspaces = useMemo(
		() => workspaces.filter((workspace) => workspace.role === "admin"),
		[workspaces],
	);
	const [email, setEmail] = useState("");
	const [role, setRole] = useState<Role>("member");
	const [teamId, setTeamId] = useState("");
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [inviteUrl, setInviteUrl] = useState<string | null>(null);
	const [copied, setCopied] = useState(false);
	const [workspaceId, setWorkspaceId] = useState("");
	const [teams, setTeams] = useState<Team[]>([]);
	const selectedWorkspaceId =
		workspaceId ||
		(adminWorkspaces.some((workspace) => workspace.id === activeWorkspaceId)
			? (activeWorkspaceId ?? "")
			: (adminWorkspaces[0]?.id ?? ""));

	useEffect(() => {
		if (!open || !selectedWorkspaceId) return;
		let current = true;
		void teamsApi.listTeams(selectedWorkspaceId)
			.then((next) => { if (current) setTeams(next); })
			.catch(() => { if (current) setTeams([]); });
		return () => { current = false; };
	}, [open, selectedWorkspaceId]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setError(null);
		setIsLoading(true);

		try {
			const invite = await invitesApi.createInvite({
				email,
				role,
				teamId: teamId || null,
				workspaceId: selectedWorkspaceId,
			});
			setInviteUrl(invite.inviteUrl);
			onInviteCreated?.(invite);
		} catch (err: unknown) {
			setError(getApiErrorMessage(err, "An error occurred"));
		} finally {
			setIsLoading(false);
		}
	};

	const handleCopy = async () => {
		if (!inviteUrl) return;
		await navigator.clipboard.writeText(inviteUrl);
		setCopied(true);
		setTimeout(() => { setCopied(false); }, 2000);
	};

	const handleClose = () => {
		setEmail("");
		setRole("member");
		setTeamId("");
		setWorkspaceId("");
		setError(null);
		setInviteUrl(null);
		setCopied(false);
		onOpenChange(false);
	};

	return (
		<Dialog
			open={open}
			onOpenChange={(nextOpen) => {
				if (nextOpen) onOpenChange(true);
				else handleClose();
			}}
		>
			<DialogContent className="sm:max-w-[440px]">
				<DialogHeader>
					<DialogTitle>Invite a member</DialogTitle>
					<DialogDescription>
						Invite someone to a workspace and optionally assign a team.
					</DialogDescription>
				</DialogHeader>

				{inviteUrl ? (
					<div className="flex flex-col gap-5">
						<p className="text-[13px] leading-5 text-label dark:text-panel-body">
							Share this link with{" "}
							<span className="font-semibold text-foreground">
								{email}
							</span>{" "}
							to invite them to the workspace.
						</p>
						<div className="flex items-center gap-2">
							<input
								aria-label="Invite link"
								readOnly
								value={inviteUrl}
								className={`${fieldClass} min-w-0 flex-1 truncate font-mono text-[12px]`}
							/>
							<DialogButton
								variant="outline"
								onClick={() => { void handleCopy(); }}
								className={copied ? "text-success dark:text-panel-success" : undefined}
							>
								{copied ? (
									<Check className="size-3.5" />
								) : (
									<Copy className="size-3.5" />
								)}
								{copied ? "Copied!" : "Copy"}
							</DialogButton>
						</div>
						<DialogFooter>
							<DialogButton onClick={handleClose}>Done</DialogButton>
						</DialogFooter>
					</div>
				) : (
					<form
						onSubmit={(e) => { void handleSubmit(e); }}
						className="flex flex-col gap-5"
					>
						{error && (
							<div className="rounded-[10px] bg-[#FBEFED] px-3.5 py-2.5 text-[13px] font-medium text-[#B04A3A] dark:bg-[#B04A3A]/10">
								{error}
							</div>
						)}

						{/* Email */}
						<div className="flex flex-col gap-[7px]">
							<label htmlFor="invite-email" className={labelClass}>
								Email
							</label>
							<input
								id="invite-email"
								type="email"
								placeholder="colleague@example.com"
								value={email}
								onChange={(e) => { setEmail(e.target.value); }}
								required
								className={fieldClass}
							/>
						</div>

						{/* Workspace */}
						<div className="flex flex-col gap-[7px]">
							<label htmlFor="invite-workspace" className={labelClass}>
								Workspace
							</label>
							<select
								id="invite-workspace"
								value={selectedWorkspaceId}
								onChange={(event) => {
									setWorkspaceId(event.target.value);
									setTeamId("");
									setTeams([]);
								}}
								required
								className={selectClass}
							>
								{adminWorkspaces.map((workspace) => (
									<option key={workspace.id} value={workspace.id}>{workspace.name}</option>
								))}
							</select>
						</div>

						{/* Role */}
						<div className="flex flex-col gap-[7px]">
							<label htmlFor="invite-role" className={labelClass}>
								Role
							</label>
							<select
								id="invite-role"
								value={role}
								onChange={(e) => { setRole(e.target.value as Role); }}
								className={selectClass}
							>
								<option value="member">Member</option>
								<option value="editor">Editor</option>
								<option value="admin">Admin</option>
							</select>
						</div>

						{/* Team */}
						<div className="flex flex-col gap-[7px]">
							<label htmlFor="invite-team" className={labelClass}>
								Team{" "}
								<span className="font-normal text-meta">(Optional)</span>
							</label>
							<select
								id="invite-team"
								value={teamId}
								onChange={(e) => { setTeamId(e.target.value); }}
								className={selectClass}
							>
								<option value="">No team</option>
								{teams.map((t) => (
									<option key={t.id} value={t.id}>
										{t.name}
									</option>
								))}
							</select>
						</div>

						<DialogFooter>
							<DialogButton
								variant="outline"
								disabled={isLoading}
								onClick={handleClose}
							>
								Cancel
							</DialogButton>
							<DialogButton
								type="submit"
								disabled={isLoading || !email.trim() || !selectedWorkspaceId}
							>
								{isLoading ? "Creating…" : "Create invite"}
							</DialogButton>
						</DialogFooter>
					</form>
				)}
			</DialogContent>
		</Dialog>
	);
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, Unplug } from "lucide-react";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { MCPAuthType, MCPServerConnection } from "@/types/mcp-servers";

function getInitials(name: string | null | undefined): string {
	if (!name) return "?";
	const parts = name.trim().split(" ");
	if (parts.length >= 2) {
		return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
	}
	return name.substring(0, 2).toUpperCase();
}

function StatusBadge({ status }: { status: MCPServerConnection["status"] }) {
	const active = status === "active";
	return (
		<span
			title={
				active
					? undefined
					: "Token expired — runs using this connection will fail until the user re-authenticates."
			}
			className={`inline-flex shrink-0 items-center gap-1.5 rounded-[4px] px-2 py-[3px] font-mono text-[9.5px] font-semibold tracking-[0.05em] ${
				active
					? "bg-success-bg text-success dark:bg-emerald-950 dark:text-emerald-300"
					: "bg-warning-bg text-warning dark:bg-amber-950 dark:text-amber-300"
			}`}
		>
			<span
				className={`size-[5px] rounded-full ${active ? "bg-success" : "bg-warning"}`}
			/>
			{active ? "ACTIVE" : "EXPIRED"}
		</span>
	);
}

/** Right panel of a non-OAuth server: nothing per-user to manage. */
function CredentialNote({ authType }: { authType: Exclude<MCPAuthType, "oauth2"> }) {
	const isApiKey = authType === "api_key";
	return (
		<div className="flex items-start gap-3.5 rounded-[10px] border border-border bg-card p-[18px]">
			<span className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-petrol-tint text-petrol">
				{isApiKey ? <KeyRound className="size-4" /> : <Unplug className="size-4" />}
			</span>
			<div className="min-w-0">
				<div className="text-[13.5px] font-semibold text-foreground">
					{isApiKey ? "Workspace credential" : "Open endpoint"}
				</div>
				<div className="mt-1 text-[12.5px] leading-[1.55] text-subtle dark:text-panel-body">
					{isApiKey
						? "Everyone uses the single API key configured on this server — there are no per-user connections to manage."
						: "This server requires no credentials — there are no per-user connections to manage."}
				</div>
			</div>
		</div>
	);
}

interface ConnectedUsersPanelProps {
	serverId: string;
	authType: MCPAuthType;
	isAdmin: boolean;
	/** Confirms + calls the reset endpoint; resolves true when it ran. */
	onResetAll: () => Promise<boolean>;
}

/**
 * CONNECTED USERS panel (detail page, OAuth servers): every user holding a
 * stored token, with status and a per-user Revoke. Admin-only — the backend
 * endpoints are admin-gated.
 */
export function ConnectedUsersPanel({
	serverId,
	authType,
	isAdmin,
	onResetAll,
}: ConnectedUsersPanelProps) {
	const [connections, setConnections] = useState<MCPServerConnection[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [revokingId, setRevokingId] = useState<string | null>(null);
	const canView = authType === "oauth2" && isAdmin;

	const fetchConnections = useCallback(async () => {
		try {
			const res = await api.get<MCPServerConnection[]>(
				`/mcp-servers/${serverId}/connections`,
			);
			setConnections(res.data);
			setError(null);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to load connections."));
		} finally {
			setIsLoading(false);
		}
	}, [serverId]);

	useEffect(() => {
		if (!canView) return;
		void fetchConnections();
	}, [canView, fetchConnections]);

	if (authType !== "oauth2") {
		return <CredentialNote authType={authType} />;
	}

	if (!isAdmin) {
		return (
			<div className="rounded-[10px] border border-dashed border-input px-5 py-8 text-center text-[13px] font-medium text-meta dark:border-white/15 dark:text-panel-dim">
				Only workspace admins can view and manage user connections.
			</div>
		);
	}

	const handleResetAll = async () => {
		if (await onResetAll()) {
			await fetchConnections();
		}
	};

	const handleRevoke = async (connection: MCPServerConnection) => {
		const who = connection.name || connection.email || "this user";
		if (
			!window.confirm(
				`Revoke ${who}'s connection? They will need to re-authenticate to use this server again.`,
			)
		)
			return;
		setRevokingId(connection.userId);
		try {
			await api.delete(`/mcp-servers/${serverId}/connections/${connection.userId}`);
			setConnections((prev) =>
				prev.filter((c) => c.userId !== connection.userId),
			);
			setError(null);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to revoke the connection."));
		} finally {
			setRevokingId(null);
		}
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="mb-3 flex flex-none items-baseline gap-2.5">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-subtle dark:text-panel-dim">
					CONNECTED USERS
				</span>
				<span className="font-mono text-[10.5px] text-meta dark:text-panel-dim">
					{isLoading ? "…" : connections.length}
				</span>
				<span className="flex-1" />
				{connections.length > 0 && (
					<button
						type="button"
						title="Revokes all user connections — users will need to re-authenticate."
						onClick={() => {
							void handleResetAll();
						}}
						className="cursor-pointer text-[12px] font-semibold text-[#B04A3A] transition-colors hover:text-destructive"
					>
						Reset all connections
					</button>
				)}
			</div>

			{error && (
				<div className="mb-3 flex-none rounded-[10px] bg-destructive/10 px-4 py-2.5 text-[12.5px] font-medium text-destructive">
					{error}
				</div>
			)}

			{/* Hugs its rows; caps at the panel height (flex shrink) and then
			    scrolls internally. */}
			<div className="min-h-0 overflow-y-auto rounded-[10px] border border-border bg-card [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				{isLoading ? (
					<div className="px-4 py-8 text-center text-[13px] font-medium text-meta dark:text-panel-dim">
						Loading connections…
					</div>
				) : connections.length === 0 ? (
					<div className="px-4 py-8 text-center text-[13px] font-medium text-meta dark:text-panel-dim">
						No one is connected to this server yet.
					</div>
				) : (
					connections.map((connection) => (
						<div
							key={connection.userId}
							className="flex items-center gap-3 border-b border-hairline px-4 py-[11px] transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5 dark:hover:bg-white/5"
						>
							<span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-ink text-[10.5px] font-bold text-white dark:bg-white/15">
								{getInitials(connection.name)}
							</span>
							<span className="min-w-0 flex-1">
								<span className="block truncate text-[13.5px] font-semibold text-foreground">
									{connection.name || "Unknown user"}
								</span>
								<span className="mt-px block truncate font-mono text-[10.5px] text-meta dark:text-panel-dim">
									{connection.email || connection.userId}
								</span>
							</span>
							<StatusBadge status={connection.status} />
							<button
								type="button"
								disabled={revokingId === connection.userId}
								onClick={() => {
									void handleRevoke(connection);
								}}
								className="cursor-pointer rounded-[7px] border border-border px-3 py-[5px] text-[12px] font-medium text-[#B04A3A] transition-colors hover:border-[#F0D5D0] hover:bg-[#FBEFED] disabled:cursor-default disabled:opacity-50 dark:hover:bg-rose-950"
							>
								{revokingId === connection.userId ? "Revoking…" : "Revoke"}
							</button>
						</div>
					))
				)}
			</div>
		</div>
	);
}

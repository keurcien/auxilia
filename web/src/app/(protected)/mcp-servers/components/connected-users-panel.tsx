"use client";

import { useCallback, useEffect, useState } from "react";
import { KeyRound, ServerCog, Unplug } from "lucide-react";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { UserAvatar } from "@/components/ui/user-avatar";
import {
	isPersonalAuth,
	MCPAuthType,
	MCPConnectionDisconnectSummary,
	MCPCredentialScope,
	MCPServerConnection,
	usesUserCredentials,
} from "@/types/mcp-servers";
import { DisconnectSummaryDialog } from "./disconnect-summary-dialog";
import { PersonalCredentialsDialog } from "./personal-credentials-dialog";

function StatusBadge({ status }: { status: MCPServerConnection["status"] }) {
	const active = status === "active";
	return (
		<span
			title={
				active
					? undefined
					: "Token expired, runs using this connection will fail until the user re-authenticates."
			}
			className={`inline-flex shrink-0 items-center gap-1.5 rounded-[4px] px-2 py-[3px] text-[9.5px] font-semibold ${
				active
					? "bg-success-bg text-success dark:bg-emerald-950 dark:text-emerald-300"
					: "bg-warning-bg text-warning dark:bg-amber-950 dark:text-amber-300"
			}`}
		>
			<span
				className={`size-[5px] rounded-full ${active ? "bg-success" : "bg-warning"}`}
			/>
			{active ? "Active" : "Expired"}
		</span>
	);
}

/** Right panel of a non-OAuth server: nothing per-user to manage. */
function CredentialNote({
	authType,
}: {
	authType: Exclude<MCPAuthType, "oauth2">;
}) {
	const isApiKey = authType === "api_key";
	const isServiceIdentity = authType === "service_identity";
	const isCustomHttp = authType === "custom_http";
	return (
		<div className="flex items-start gap-3.5 rounded-[10px] border border-border bg-card p-[18px]">
			<span className="flex size-[34px] shrink-0 items-center justify-center rounded-[9px] bg-petrol-tint text-petrol dark:bg-white/10 dark:text-panel-terminal">
				{isApiKey || isCustomHttp ? (
					<KeyRound className="size-4" />
				) : isServiceIdentity ? (
					<ServerCog className="size-4" />
				) : (
					<Unplug className="size-4" />
				)}
			</span>
			<div className="min-w-0">
				<div className="text-[13.5px] font-semibold text-foreground">
					{isApiKey
						? "Workspace credential"
						: isCustomHttp
							? "Custom HTTP headers"
							: isServiceIdentity
								? "Service identity"
								: "Open endpoint"}
				</div>
				<div className="mt-1 text-[12.5px] leading-[1.55] text-subtle dark:text-panel-body">
					{isApiKey
						? "Everyone uses the single API key configured on this server, there are no per-user connections to manage."
						: isCustomHttp
							? "Every request uses the encrypted HTTP headers configured on this server; there are no per-user connections to manage."
							: isServiceIdentity
								? "Everyone uses the managed service identity configured on this server, while access remains controlled by workspace visibility and agent permissions."
								: "This server requires no credentials, there are no per-user connections to manage."}
				</div>
			</div>
		</div>
	);
}

interface ConnectedUsersPanelProps {
	serverId: string;
	serverName: string;
	authType: MCPAuthType;
	credentialScope?: MCPCredentialScope;
	personalHeaderNames?: string[];
	isAdmin: boolean;
	/** Confirms + calls the reset endpoint; resolves true when it ran. */
	onResetAll: () => Promise<boolean>;
	onReconnect: () => void;
	connectionRevision: string;
}

/**
 * CONNECTED USERS panel (detail page, personal servers): every user holding a
 * stored OAuth token or their own API key / header values, with status and a
 * per-user Revoke. Admin-only — the backend endpoints are admin-gated.
 */
export function ConnectedUsersPanel({
	serverId,
	serverName,
	authType,
	credentialScope,
	personalHeaderNames,
	isAdmin,
	onResetAll,
	onReconnect,
	connectionRevision,
}: ConnectedUsersPanelProps) {
	const personal = isPersonalAuth({ authType, credentialScope });
	const userEntered = usesUserCredentials({ authType, credentialScope });
	const [credentialsOpen, setCredentialsOpen] = useState(false);
	const confirmDialog = useConfirmDialog();
	const [connections, setConnections] = useState<MCPServerConnection[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [revokingId, setRevokingId] = useState<string | null>(null);
	const [personalConnected, setPersonalConnected] = useState<boolean | null>(null);
	const [personalError, setPersonalError] = useState<string | null>(null);
	const [isDisconnecting, setIsDisconnecting] = useState(false);
	const [disconnectSummary, setDisconnectSummary] =
		useState<MCPConnectionDisconnectSummary | null>(null);
	const [summaryOpen, setSummaryOpen] = useState(false);
	const canView = personal && isAdmin;

	const fetchConnections = useCallback(async () => {
		try {
			setConnections(await mcpServersApi.listMcpServerConnections(serverId));
			setError(null);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to load connections."));
		} finally {
			setIsLoading(false);
		}
	}, [serverId]);

	useEffect(() => {
		if (!canView) return;
		let active = true;
		void mcpServersApi
			.listMcpServerConnections(serverId)
			.then((nextConnections) => {
				if (!active) return;
				setConnections(nextConnections);
				setError(null);
			})
			.catch((err: unknown) => {
				if (!active) return;
				setError(getApiErrorMessage(err, "Failed to load connections."));
			})
			.finally(() => {
				if (active) setIsLoading(false);
			});
		return () => {
			active = false;
		};
	}, [canView, serverId]);

	useEffect(() => {
		if (!personal) return;
		let active = true;
		setPersonalConnected(null);
		void mcpServersApi
			.isMcpServerConnected(serverId)
			.then((connected) => {
				if (!active) return;
				setPersonalConnected(connected);
				setPersonalError(null);
			})
			.catch((err: unknown) => {
				if (!active) return;
				setPersonalError(
					getApiErrorMessage(err, "Failed to load your connection status."),
				);
			});
		return () => {
			active = false;
		};
	}, [personal, connectionRevision, serverId]);

	if (!personal && authType !== "oauth2") {
		return <CredentialNote authType={authType} />;
	}

	const handleResetAll = async () => {
		if (await onResetAll()) {
			await fetchConnections();
		}
	};

	const handlePersonalDisconnect = async () => {
		if (
			!(await confirmDialog({
				title: userEntered
					? "Remove your credentials?"
					: "Disconnect your account?",
				description: userEntered
					? "Your saved credentials will be deleted. You will need to enter them again before using this MCP server. Other users are not affected."
					: "You will need to reconnect before using this MCP server again. Other users and shared credentials are not affected.",
				confirmLabel: userEntered
					? "Remove my credentials"
					: "Disconnect my account",
				destructive: true,
			}))
		)
			return;
		setIsDisconnecting(true);
		setPersonalError(null);
		try {
			const result = await mcpServersApi.disconnectMyMcpConnection(serverId);
			setDisconnectSummary(result);
			setSummaryOpen(true);
			if (result.failed.length === 0) setPersonalConnected(false);
			if (isAdmin) await fetchConnections();
		} catch (err) {
			setPersonalError(
				getApiErrorMessage(err, "Failed to disconnect your account."),
			);
		} finally {
			setIsDisconnecting(false);
		}
	};

	const handleRevoke = async (connection: MCPServerConnection) => {
		const who = connection.name || connection.email || "this user";
		if (
			!(await confirmDialog({
				title: `Revoke ${who}’s connection?`,
				description:
					"They will need to authenticate again before they can use this MCP server.",
				confirmLabel: "Revoke connection",
				destructive: true,
			}))
		)
			return;
		setRevokingId(connection.userId);
		try {
			await mcpServersApi.deleteMcpServerConnection(
				serverId,
				connection.userId,
			);
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
			<div className="rounded-[10px] border border-border bg-card p-4">
				<div className="flex items-center gap-3">
					<div className="min-w-0 flex-1">
						<p className="text-[13.5px] font-semibold text-foreground">
							Your connection
						</p>
						<p className="mt-0.5 text-[12px] text-meta dark:text-panel-dim">
							{personalConnected === null
								? "Checking your account…"
								: userEntered
									? personalConnected
										? authType === "api_key"
											? "Your personal API key is saved."
											: "Your personal header values are saved."
										: authType === "api_key"
											? "You have not entered your API key yet."
											: "You have not entered your header values yet."
									: personalConnected
										? "Your personal OAuth account is connected."
										: "No personal account is connected."}
						</p>
					</div>
					{userEntered && personalConnected !== null && (
						<button
							type="button"
							onClick={() => {
								setCredentialsOpen(true);
							}}
							className={
								personalConnected
									? "cursor-pointer rounded-[7px] border border-border px-3 py-[6px] text-[12px] font-semibold text-foreground transition-colors hover:bg-hover dark:hover:bg-white/5"
									: "cursor-pointer rounded-[7px] bg-petrol px-3 py-[6px] text-[12px] font-semibold text-white transition-colors hover:bg-petrol/90"
							}
						>
							{personalConnected ? "Replace" : "Connect"}
						</button>
					)}
					{!userEntered && personalConnected === false && (
						<button
							type="button"
							onClick={() => {
								onReconnect();
							}}
							className="cursor-pointer rounded-[7px] bg-petrol px-3 py-[6px] text-[12px] font-semibold text-white transition-colors hover:bg-petrol/90"
						>
							Reconnect
						</button>
					)}
					{personalConnected === true && (
						<button
							type="button"
							disabled={isDisconnecting}
							onClick={() => {
								void handlePersonalDisconnect();
							}}
							className="cursor-pointer rounded-[7px] border border-border px-3 py-[6px] text-[12px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] disabled:cursor-default disabled:opacity-50 dark:hover:bg-rose-950"
						>
							{isDisconnecting
								? "Disconnecting…"
								: userEntered
									? "Remove"
									: "Disconnect my account"}
						</button>
					)}
				</div>
				{personalError && (
					<p className="mt-3 rounded-[8px] bg-destructive/10 px-3 py-2 text-[12px] text-destructive">
						{personalError}
					</p>
				)}
			</div>

			{isAdmin && (
				<div className="mt-5 flex min-h-0 flex-1 flex-col">
					<div className="mb-3 flex flex-none items-baseline gap-2.5">
						<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
							Connected users
						</span>
						<span className="text-[10.5px] text-meta dark:text-panel-dim">
							{isLoading ? (
								"…"
							) : error && connections.length === 0 ? (
								"Not available"
							) : (
								<span className="font-mono">{connections.length}</span>
							)}
						</span>
						<span className="flex-1" />
						{connections.length > 0 && (
							<button
								type="button"
								title="Revokes all user connections, users will need to re-authenticate."
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

					<div className="min-h-0 overflow-y-auto rounded-[10px] border border-border bg-card [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
						{isLoading ? (
							<div className="px-4 py-8 text-center text-[13px] font-medium text-meta dark:text-panel-dim">
								Loading connections…
							</div>
						) : error && connections.length === 0 ? (
							<div className="px-4 py-8 text-center">
								<button
									type="button"
									onClick={() => {
										setIsLoading(true);
										void fetchConnections();
									}}
									className="cursor-pointer text-[13px] font-semibold text-petrol hover:underline dark:text-panel-terminal"
								>
									Retry loading connections
								</button>
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
									<UserAvatar
										name={connection.name}
										pictureUrl={connection.pictureUrl}
										userId={connection.userId}
										imageRevision={connection.imageRevision}
										className="shrink-0"
									/>
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
										{revokingId === connection.userId
											? "Revoking…"
											: "Revoke"}
									</button>
								</div>
							))
						)}
					</div>
				</div>
			)}

			<DisconnectSummaryDialog
				open={summaryOpen}
				onOpenChange={setSummaryOpen}
				summary={disconnectSummary}
				title="Your MCP account disconnect report"
			/>
			{userEntered && (
				<PersonalCredentialsDialog
					server={
						credentialsOpen
							? { id: serverId, name: serverName, authType, personalHeaderNames }
							: null
					}
					onOpenChange={setCredentialsOpen}
					onSaved={() => {
						setCredentialsOpen(false);
						setPersonalConnected(true);
						setPersonalError(null);
						if (isAdmin) void fetchConnections();
					}}
				/>
			)}
		</div>
	);
}

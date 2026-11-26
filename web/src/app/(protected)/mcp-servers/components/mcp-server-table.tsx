"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, X } from "lucide-react";
import { toast } from "sonner";
import {
	BulkConfirmDialog,
	type BulkConfirmItem,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { BulkActionBar } from "@/components/ui/bulk-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { RowActionLink } from "@/components/ui/row-action-link";
import { GroupedCardTree } from "@/components/ui/grouped-card-tree";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import { LONG_PRESS_TARGET_CLASS, useLongPress } from "@/hooks/use-long-press";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import type { ViewMode } from "@/components/ui/view-toggle";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import ResourceInUseDialog from "@/components/resource-in-use-dialog";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { useDeleteMcpServer } from "@/hooks/use-delete-mcp-server";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useUserStore } from "@/stores/user-store";
import { isPersonalAuth, MCPServer } from "@/types/mcp-servers";
import { getApiErrorMessage, toApiError } from "@/lib/api/errors";
import { deleteDatabaseConnection } from "@/lib/api/resources/database-connections";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { buildGroupTree, flattenGroupTree } from "@/lib/groups";
import { useRowSelection } from "@/hooks/use-row-selection";
import {
	matchesResourceScope,
	type ResourceScopeFilter,
} from "@/lib/resource-scope-filter";
import { AuthTypeBadge } from "./auth-type-badge";
import {
	matchesCredentialScope,
	type CredentialScopeFilter,
} from "./credential-scope-filter";
import { OAuthConnectionFollowUpDialog } from "./oauth-connection-follow-up-dialog";
import { PersonalCredentialsDialog } from "./personal-credentials-dialog";
import { ServerIconTile } from "./server-icon-tile";
import { useConnectionTest } from "../lib/use-connection-test";

interface MCPServerTableProps {
	mode: ViewMode;
	search: string;
	scope: ResourceScopeFilter;
	filterTeamIds: string[];
	credentialScope: CredentialScopeFilter;
	onClearSearch: () => void;
}

function serverHref(server: MCPServer): string {
	return `/mcp-servers/${server.id}`;
}

function serverEditHref(server: MCPServer): string {
	return server.managedBy === "database" && server.managedResourceId
		? `/mcp-servers/database/${server.managedResourceId}`
		: `${serverHref(server)}?edit=1`;
}

/** Row-scoped Test button: label reflects the last run, tooltip carries the
 * full result message. */
function RowTestButton({ server }: { server: MCPServer }) {
	const {
		status,
		message,
		oauthFollowUpOpen,
		setOauthFollowUpOpen,
		runSavedTest,
		verifySavedConnection,
		credentialsServer,
		closeCredentialsPrompt,
		completeCredentials,
	} = useConnectionTest();
	const [isVerifying, setIsVerifying] = useState(false);

	const handleVerify = async () => {
		setIsVerifying(true);
		await verifySavedConnection(server.id);
		setIsVerifying(false);
	};

	return (
		<>
			<button
				type="button"
				title={message ?? "Test the connection as you"}
				disabled={status === "testing"}
				onClick={() => {
					void runSavedTest(server);
				}}
				className={`flex cursor-pointer items-center gap-1 rounded-[7px] border border-border px-[11px] py-[5px] text-[12px] font-semibold transition-colors hover:bg-sidebar disabled:cursor-default dark:hover:bg-white/5 ${
					status === "error" ? "text-destructive" : "text-petrol"
				}`}
			>
				{status === "success" && <Check className="size-3" />}
				{status === "error" && <X className="size-3" />}
				{status === "testing" ? "Testing…" : "Test"}
			</button>
			<OAuthConnectionFollowUpDialog
				open={oauthFollowUpOpen}
				onOpenChange={setOauthFollowUpOpen}
				onVerify={() => {
					void handleVerify();
				}}
				isVerifying={isVerifying}
				message={message === "Waiting for authentication…" ? null : message}
			/>
			<PersonalCredentialsDialog
				server={credentialsServer}
				onOpenChange={(open) => {
					if (!open) closeCredentialsPrompt();
				}}
				onSaved={completeCredentials}
			/>
		</>
	);
}

export default function MCPServerTable({
	mode,
	search,
	scope,
	filterTeamIds,
	credentialScope,
	onClearSearch,
}: MCPServerTableProps) {
	const confirmDialog = useConfirmDialog();
	const router = useRouter();
	const isAdmin = useUserStore((state) => state.user?.role === "admin");
	const {
		mcpServers,
		fetchMcpServers,
		isInitialized,
		deleteMcpServer,
		duplicateMcpServer,
		refreshMcpServers,
		resetMcpServerConnections,
	} = useMcpServersStore();
	const [isLoading, setIsLoading] = useState(true);
	const [loadError, setLoadError] = useState<string | null>(null);
	// Delete/reset failures render inline — they must not hide the table.
	const [actionError, setActionError] = useState<string | null>(null);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);
	const [bulkOpen, setBulkOpen] = useState(false);
	const [bulkItems, setBulkItems] = useState<BulkConfirmItem[]>([]);
	const [bulkDetachIds, setBulkDetachIds] = useState<Set<string>>(
		() => new Set(),
	);

	useEffect(() => {
		const load = async () => {
			if (isInitialized) {
				setIsLoading(false);
				return;
			}
			setIsLoading(true);
			try {
				await fetchMcpServers();
				setLoadError(null);
			} catch (err) {
				setLoadError(getApiErrorMessage(err, "Failed to load MCP servers."));
			} finally {
				setIsLoading(false);
			}
		};
		void load();
	}, [fetchMcpServers, isInitialized]);

	const filtered = useMemo(() => {
		const query = search.trim().toLowerCase();
		return mcpServers.filter(
			(server) =>
				matchesResourceScope(server, scope, filterTeamIds) &&
				matchesCredentialScope(server, credentialScope) &&
				(!query ||
					server.name.toLowerCase().includes(query) ||
					server.url.toLowerCase().includes(query) ||
					(server.description ?? "").toLowerCase().includes(query) ||
					(server.group ?? "").toLowerCase().includes(query)),
		);
	}, [credentialScope, filterTeamIds, mcpServers, scope, search]);
	const filtersActive = scope !== "all" || credentialScope !== "all";
	const groupTree = useMemo(() => buildGroupTree(filtered), [filtered]);
	const orderedServers = useMemo(() => flattenGroupTree(groupTree), [groupTree]);
	const selectableServerIds = useMemo(
		() => (isAdmin ? orderedServers.map((server) => server.id) : []),
		[isAdmin, orderedServers],
	);
	const longPress = useLongPress();
	const selection = useRowSelection({
		orderedIds: orderedServers.map((server) => server.id),
		eligibleIds: selectableServerIds,
	});

	const prepareBulkDelete = async () => {
		const selected = orderedServers.filter((server) =>
			selection.selectedIds.has(server.id),
		);
		const checks = await Promise.allSettled(
			selected.map((server) => mcpServersApi.listMcpServerAgents(server.id)),
		);
		const detachIds = new Set<string>();
		setBulkItems(
			selected.map((server, index) => {
				const result = checks.at(index);
				if (server.managedBy === "database" && !server.managedResourceId) {
					return {
						id: server.id,
						name: server.name,
						blockedReason: "Its managed database connection could not be found.",
					};
				}
				if (!result) {
					return {
						id: server.id,
						name: server.name,
						blockedReason: "Could not verify its agent connections.",
					};
				}
				if (result.status === "rejected") {
					return {
						id: server.id,
						name: server.name,
						blockedReason: "Could not verify its agent connections.",
					};
				}
				if (result.value.length > 0) {
					detachIds.add(server.id);
					return {
						id: server.id,
						name: server.name,
						note: `Will be detached from ${result.value.length} agent${
							result.value.length === 1 ? "" : "s"
						}.`,
					};
				}
				return { id: server.id, name: server.name };
			}),
		);
		setBulkDetachIds(detachIds);
		setBulkOpen(true);
	};

	const {
		guard: deleteGuard,
		clearGuard: clearDeleteGuard,
		requestDelete,
		confirmDetachAndDelete,
	} = useDeleteMcpServer({
		onError: (err) => {
			setActionError(getApiErrorMessage(err, "Failed to delete MCP server."));
		},
		onForbidden: () => {
			setForbiddenOpen(true);
		},
	});

	const handleDelete = async (server: MCPServer) => {
		// A stale failure banner must not outlive the next action.
		setActionError(null);
		await requestDelete(server);
	};

	const handleDeleteDatabase = async (server: MCPServer) => {
		if (!server.managedResourceId) return;
		if (
			!(await confirmDialog({
				title: `Delete “${server.name}”?`,
				description:
					"The database connection and its managed MCP server will be removed permanently.",
				confirmLabel: "Delete connection",
				destructive: true,
			}))
		)
			return;

		setActionError(null);
		try {
			await deleteDatabaseConnection(server.managedResourceId);
		} catch (error) {
			if (toApiError(error).status !== 400) {
				setActionError(
					getApiErrorMessage(error, "Failed to delete database connection."),
				);
				return;
			}
			if (
				!(await confirmDialog({
					title: "Detach agents and delete?",
					description:
						"This connection is still attached to one or more agents. It must be detached before it can be deleted.",
					confirmLabel: "Detach and delete",
					destructive: true,
				}))
			)
				return;
			try {
				await deleteDatabaseConnection(server.managedResourceId, {
					detachAgents: true,
				});
			} catch (detachError) {
				setActionError(
					getApiErrorMessage(
						detachError,
						"Failed to delete database connection.",
					),
				);
				return;
			}
		}
		await refreshMcpServers();
	};

	const handleReset = async (server: MCPServer) => {
		if (
			!(await confirmDialog({
				title: "Reset all connections?",
				description:
					"Every user connection to this MCP server will be revoked. Users will need to authenticate again.",
				confirmLabel: "Reset connections",
				destructive: true,
			}))
		)
			return;
		// A stale failure banner must not outlive the next action.
		setActionError(null);
		try {
			await resetMcpServerConnections(server.id);
		} catch (err: unknown) {
			if (err instanceof Object && "status" in err && err.status === 403) {
				setForbiddenOpen(true);
			} else {
				setActionError(
					getApiErrorMessage(err, "Failed to reset MCP server connections."),
				);
			}
		}
	};

	const handleDuplicate = async (server: MCPServer) => {
		setActionError(null);
		try {
			const created = await duplicateMcpServer(server.id);
			toast.success(`Duplicated as “${created.name}”.`);
			router.push(`/mcp-servers/${created.id}?edit=1`);
		} catch (err: unknown) {
			if (toApiError(err).status === 403) {
				setForbiddenOpen(true);
			} else {
				setActionError(
					getApiErrorMessage(err, "Could not duplicate the MCP server."),
				);
			}
		}
	};

	const serverMenuItems = (server: MCPServer) =>
		server.managedBy === "database"
			? [
					{
						label: "Delete database",
						destructive: true,
						onClick: () => {
							void handleDeleteDatabase(server);
						},
					},
				]
			: [
					{
						label: "Duplicate",
						onClick: () => {
							void handleDuplicate(server);
						},
					},
					...(isPersonalAuth(server)
						? [
								{
									label: "Reset connections",
									onClick: () => {
										void handleReset(server);
									},
								},
							]
						: []),
					{
						label: "Delete server",
						destructive: true,
						onClick: () => {
							void handleDelete(server);
						},
					},
				];

	const columns: DataTableColumn<MCPServer>[] = [
		{
			key: "server",
			header: selection.selectionMode ? (
				""
			) : (
				<span className="flex items-center gap-3">
					<Checkbox
						checked={false}
						aria-label="Select all deletable MCP servers"
						disabled={selectableServerIds.length === 0}
						onCheckedChange={selection.toggleAll}
					/>
					<button
						type="button"
						disabled={selectableServerIds.length === 0}
						onClick={selection.toggleAll}
						className="cursor-pointer text-[12px]! font-semibold text-foreground hover:text-petrol disabled:cursor-not-allowed disabled:opacity-35"
					>
						Select all
					</button>
				</span>
			),
			width: "minmax(220px, 1.35fr)",
			cell: (server) => (
				<div className="flex min-w-0 items-center gap-3">
					<SelectableLeading
						selected={selection.isSelected(server.id)}
						selectionMode={selection.selectionMode}
						disabled={!isAdmin}
						label={`Select ${server.name}`}
						onToggle={(shiftKey) => {
							selection.toggle(server.id, shiftKey);
						}}
						className="size-8"
					>
						<ServerIconTile
							iconUrl={server.iconUrl}
							serverId={server.id}
							imageRevision={server.imageRevision}
							name={server.name}
							size={32}
						/>
					</SelectableLeading>
					<div className="min-w-0">
						<div className="truncate text-[13.5px] font-semibold text-foreground">
							{server.name}
						</div>
						<div className="mt-px truncate text-[12px] text-subtle dark:text-muted-foreground">
							{server.description || "No description provided."}
						</div>
					</div>
				</div>
			),
		},
		{
			key: "endpoint",
			header: "Endpoint",
			width: "220px",
			cell: (server) => (
				<span className="block truncate font-mono text-[11px] text-subtle dark:text-muted-foreground">
					{server.managedBy === "database"
						? (server.managedEndpoint ?? "Managed database")
						: server.url}
				</span>
			),
		},
		{
			key: "auth",
			header: "Auth",
			width: "110px",
			mobileWidth: "auto",
			cell: (server) => <AuthTypeBadge
				authType={server.authType}
				credentialScope={server.credentialScope}
			/>,
		},
		{
			key: "visibility",
			header: "Visibility",
			width: "120px",
			cell: (server) => (
				<VisibilityBadge
					visibility={server.visibility ?? "workspace"}
					teamIds={server.teamIds}
				/>
			),
		},
		{
			key: "actions",
			header: "",
			width: "170px",
			mobileWidth: "auto",
			cell: (server) => (
				<div
					className="flex items-center justify-end gap-1.5"
					// The row itself is clickable — keep action clicks off it.
					onClick={(e) => {
						e.stopPropagation();
					}}
				>
					<RowTestButton server={server} />
					{isAdmin && (
						<>
							<RowActionLink href={serverEditHref(server)}>
								Edit
							</RowActionLink>
							<DropdownMenu items={serverMenuItems(server)} />
						</>
					)}
				</div>
			),
		},
	];

	if (loadError) {
		return (
			<div className="flex items-center justify-center rounded-[10px] border border-border p-12">
				<div className="text-[14px] font-medium text-destructive">{loadError}</div>
			</div>
		);
	}

	return (
		<>
			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="Insufficient privileges"
				message="You are not allowed to perform this action."
			/>
			<ResourceInUseDialog
				open={deleteGuard !== null}
				onOpenChange={(open) => {
					if (!open) clearDeleteGuard();
				}}
				resourceLabel="MCP server"
				resourceName={deleteGuard?.server.name ?? null}
				agents={deleteGuard?.agents ?? []}
				consequence="access to its tools"
				onConfirm={confirmDetachAndDelete}
			/>
			{actionError && (
				<div className="mb-3 shrink-0 rounded-[10px] bg-destructive/10 px-4 py-2.5 text-[13px] font-medium text-destructive">
					{actionError}
				</div>
			)}
			<BulkConfirmDialog
				open={bulkOpen}
				onOpenChange={setBulkOpen}
				title="Delete selected connections?"
				description="The selected MCP servers and database connections will be removed permanently. Connections used by agents will first be detached from them."
				items={bulkItems}
				confirmLabel="Delete"
				busyLabel="Deleting…"
				acknowledgement={
					bulkDetachIds.size > 0
						? "I understand that these connections will be removed from every agent using them and deleted permanently."
						: undefined
				}
				onConfirm={async (items) => {
					const results = await Promise.allSettled(
						items.map((item) => {
							const server = orderedServers.find(
								(candidate) => candidate.id === item.id,
							);
							if (
								server?.managedBy === "database" &&
								server.managedResourceId
							) {
								return deleteDatabaseConnection(server.managedResourceId, {
									detachAgents: bulkDetachIds.has(item.id),
								});
							}
							return deleteMcpServer(item.id, {
								detachAgents: bulkDetachIds.has(item.id),
							});
						}),
					);
					const succeeded: string[] = [];
					const failures: BulkFailure[] = [];
					let deletedDatabase = false;
					results.forEach((result, index) => {
						const item = items.at(index);
						if (!item) return;
						if (result.status === "fulfilled") {
							succeeded.push(item.id);
							const server = orderedServers.find(
								(candidate) => candidate.id === item.id,
							);
							if (server?.managedBy === "database") {
								deletedDatabase = true;
							}
						} else {
							failures.push({
								id: item.id,
								name: item.name,
								message: getApiErrorMessage(result.reason, "Delete failed."),
							});
						}
					});
					if (deletedDatabase) {
						try {
							await refreshMcpServers();
						} catch (error) {
							setActionError(
								getApiErrorMessage(
									error,
									"Connections were deleted, but the list could not be refreshed.",
								),
							);
						}
					}
					selection.remove(succeeded);
					return failures;
				}}
			/>
			<BulkActionBar
				selectedCount={selection.selectedCount}
				totalCount={selectableServerIds.length}
				allSelected={selection.allSelected}
				someSelected={selection.someSelected}
				onToggleAll={selection.toggleAll}
				onClear={selection.clear}
				actionLabel="Delete"
				onAction={() => {
					void prepareBulkDelete();
				}}
				showWhenEmpty={mode === "cards"}
			/>
			{mode === "cards" ? (
				isLoading ? null : filtered.length === 0 ? (
					<div className="flex min-h-48 items-center justify-center rounded-[10px] border border-dashed border-border px-6 text-center text-[13px] text-subtle">
						{search && mcpServers.length > 0 ? (
							<span>
								No servers match your search.{" "}
								<button
									type="button"
									onClick={onClearSearch}
									className="cursor-pointer font-semibold text-petrol hover:underline dark:text-panel-terminal"
								>
									Clear search
								</button>
							</span>
						) : filtersActive && mcpServers.length > 0 ? (
							"No MCP server matches these filters."
						) : (
							"No MCP servers configured. Add one to get started."
						)}
					</div>
				) : (
					<GroupedCardTree
						tree={groupTree}
						storageKey="mcp-servers:card-group"
						renderItem={(server, index) => (
							<article
								key={server.id}
								className={`group relative flex min-h-[190px] animate-in flex-col rounded-xl border bg-white p-4 fade-in slide-in-from-bottom-3 transition-[border-color,box-shadow] duration-400 ease-out hover:shadow-[0_3px_10px_rgba(30,45,40,0.06)] dark:bg-card ${
									selection.isSelected(server.id)
										? "border-petrol/45 shadow-[inset_0_0_0_1px_rgba(38,103,81,0.12)] dark:border-petrol/60"
										: "border-[#e1ebe6] hover:border-[#cfe0d8] dark:border-white/10 dark:hover:border-white/20"
								}`}
								style={{
									animationDelay: `${index * 40}ms`,
									animationFillMode: "both",
								}}
							>
								<Link
									href={serverHref(server)}
									{...longPress.bind(
										isAdmin
											? () => {
													if (!selection.isSelected(server.id)) {
														selection.toggle(server.id);
													}
												}
											: undefined,
									)}
									onClickCapture={longPress.onClickCapture}
									onClick={(event) => {
										if (
											!selection.selectionMode ||
											!isAdmin
										)
											return;
										event.preventDefault();
										selection.toggle(server.id, event.shiftKey);
									}}
									className={`absolute inset-0 rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-petrol ${
										isAdmin ? LONG_PRESS_TARGET_CLASS : ""
									}`}
								>
									<span className="sr-only">Open {server.name}</span>
								</Link>
								<div className="pointer-events-none flex min-w-0 items-center gap-3">
									<SelectableLeading
										selected={selection.isSelected(server.id)}
										selectionMode={selection.selectionMode}
										disabled={!isAdmin}
										label={`Select ${server.name}`}
										onToggle={(shiftKey) => {
											selection.toggle(server.id, shiftKey);
										}}
										className="pointer-events-auto z-10 size-[38px]"
									>
										<ServerIconTile
											iconUrl={server.iconUrl}
											serverId={server.id}
											imageRevision={server.imageRevision}
											name={server.name}
											size={38}
										/>
									</SelectableLeading>
									<div className="min-w-0 flex-1">
										<h2 className="truncate text-[14.5px] font-bold tracking-[-0.01em] text-foreground">
											{server.name}
										</h2>
										<div className="mt-1 flex flex-wrap items-center gap-1.5">
											<AuthTypeBadge
				authType={server.authType}
				credentialScope={server.credentialScope}
			/>
											<VisibilityBadge
												visibility={server.visibility ?? "workspace"}
												teamIds={server.teamIds}
											/>
										</div>
									</div>
								</div>
								<p className="pointer-events-none mt-3 line-clamp-2 min-h-[38px] flex-1 text-[12.5px] leading-[1.5] text-subtle dark:text-muted-foreground">
									{server.description || "No description provided."}
								</p>
								<p className="pointer-events-none mt-3 truncate border-t border-[#edf2ef] pt-3 font-mono text-[10.5px] text-meta dark:border-white/5 dark:text-panel-dim">
									{server.managedBy === "database"
										? (server.managedEndpoint ?? "Managed database")
										: server.url}
								</p>
								<div className="relative z-10 mt-3 flex flex-wrap items-center justify-end gap-1.5">
									<RowTestButton server={server} />
									{isAdmin && (
										<>
											<RowActionLink href={serverEditHref(server)}>
												Edit
											</RowActionLink>
											<DropdownMenu items={serverMenuItems(server)} />
										</>
									)}
								</div>
							</article>
						)}
					/>
				)
			) : (
				<DataTable
					columns={columns}
					rows={filtered}
					rowKey={(server) => server.id}
					isRowSelected={(server) => selection.isSelected(server.id)}
					selectionMode={selection.selectionMode}
					onRowSelectionClick={(server, shiftKey) => {
						selection.toggle(server.id, shiftKey);
					}}
					isRowSelectable={() => isAdmin}
					isLoading={isLoading}
					scrollBody
					minTableWidth="950px"
					bleedOnNarrow
					groupTree={{
						...groupTree,
						storageKey: "mcp-servers:table-group",
					}}
					// Rows navigate via onRowClick, not a Link — the action buttons
					// live inside the row, and interactive elements can't nest in <a>.
					onRowClick={(server) => {
						router.push(serverHref(server));
					}}
					emptyMessage={
						search && mcpServers.length > 0 ? (
							<span>
								No servers match your search.{" "}
								<button
									type="button"
									onClick={onClearSearch}
									className="cursor-pointer font-semibold text-petrol hover:underline dark:text-panel-terminal"
								>
									Clear search
								</button>
							</span>
						) : filtersActive && mcpServers.length > 0 ? (
							"No MCP server matches these filters."
						) : (
							"No MCP servers configured. Add one to get started."
						)
					}
				/>
			)}
		</>
	);
}

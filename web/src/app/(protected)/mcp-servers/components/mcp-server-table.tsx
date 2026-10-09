"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Check, X } from "lucide-react";
import {
	BulkConfirmDialog,
	type BulkConfirmItem,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { BulkActionBar } from "@/components/ui/bulk-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { GroupedCardTree } from "@/components/ui/grouped-card-tree";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import type { ViewMode } from "@/components/ui/view-toggle";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import ResourceInUseDialog from "@/components/resource-in-use-dialog";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { useDeleteMcpServer } from "@/hooks/use-delete-mcp-server";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useUserStore } from "@/stores/user-store";
import { MCPServer } from "@/types/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { buildGroupTree, flattenGroupTree } from "@/lib/groups";
import { useRowSelection } from "@/hooks/use-row-selection";
import {
	matchesResourceScope,
	type ResourceScopeFilter,
} from "@/lib/resource-scope-filter";
import { AuthTypeBadge } from "./auth-type-badge";
import { ServerIconTile } from "./server-icon-tile";
import { useConnectionTest } from "../lib/use-connection-test";

interface MCPServerTableProps {
	mode: ViewMode;
	search: string;
	scope: ResourceScopeFilter;
	filterTeamIds: string[];
	onClearSearch: () => void;
}

/** Row-scoped Test button: label reflects the last run, tooltip carries the
 * full result message. */
function RowTestButton({ server }: { server: MCPServer }) {
	const { status, message, runSavedTest } = useConnectionTest();

	return (
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
	);
}

export default function MCPServerTable({
	mode,
	search,
	scope,
	filterTeamIds,
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
				(!query ||
					server.name.toLowerCase().includes(query) ||
					server.url.toLowerCase().includes(query) ||
					(server.description ?? "").toLowerCase().includes(query) ||
					(server.group ?? "").toLowerCase().includes(query)),
		);
	}, [filterTeamIds, mcpServers, scope, search]);
	const groupTree = useMemo(() => buildGroupTree(filtered), [filtered]);
	const orderedServers = useMemo(() => flattenGroupTree(groupTree), [groupTree]);
	const selection = useRowSelection({
		orderedIds: orderedServers.map((server) => server.id),
		eligibleIds: isAdmin ? orderedServers.map((server) => server.id) : [],
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

	const columns: DataTableColumn<MCPServer>[] = [
		{
			key: "server",
			header: selection.selectionMode ? (
				""
			) : (
				<span className="flex items-center gap-3">
					<Checkbox
						checked={false}
						aria-label="Select all MCP servers"
						disabled={!isAdmin}
						onCheckedChange={selection.toggleAll}
					/>
					<button
						type="button"
						disabled={!isAdmin}
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
					{server.url}
				</span>
			),
		},
		{
			key: "auth",
			header: "Auth",
			width: "110px",
			mobileWidth: "auto",
			cell: (server) => <AuthTypeBadge authType={server.authType} />,
		},
		{
			key: "visibility",
			header: "Visibility",
			width: "120px",
			cell: (server) => (
				<VisibilityBadge visibility={server.visibility ?? "workspace"} />
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
							<button
								type="button"
								onClick={() => {
									router.push(`/mcp-servers/${server.id}?edit=1`);
								}}
								className="cursor-pointer rounded-[7px] border border-border px-[11px] py-[5px] text-[12px] font-medium text-body transition-colors hover:bg-sidebar dark:text-panel-body dark:hover:bg-white/5"
							>
								Edit
							</button>
							<DropdownMenu
								items={[
									...(server.authType === "oauth2"
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
								]}
							/>
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
				consequence="they lose its tools"
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
				title="Delete selected MCP servers?"
				description="The servers will be removed permanently. Servers used by agents will first be detached from them."
				items={bulkItems}
				confirmLabel="Delete"
				busyLabel="Deleting…"
				onConfirm={async (items) => {
					const results = await Promise.allSettled(
						items.map((item) =>
							deleteMcpServer(item.id, {
								detachAgents: bulkDetachIds.has(item.id),
							}),
						),
					);
					const succeeded: string[] = [];
					const failures: BulkFailure[] = [];
					results.forEach((result, index) => {
						const item = items.at(index);
						if (!item) return;
						if (result.status === "fulfilled") succeeded.push(item.id);
						else
							failures.push({
								id: item.id,
								name: item.name,
								message: getApiErrorMessage(result.reason, "Delete failed."),
							});
					});
					selection.remove(succeeded);
					return failures;
				}}
			/>
			<BulkActionBar
				selectedCount={selection.selectedCount}
				totalCount={isAdmin ? orderedServers.length : 0}
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
						) : scope !== "all" && mcpServers.length > 0 ? (
							"No MCP server matches this visibility filter."
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
									href={`/mcp-servers/${server.id}`}
									onClick={(event) => {
										if (!selection.selectionMode || !isAdmin) return;
										event.preventDefault();
										selection.toggle(server.id, event.shiftKey);
									}}
									className="absolute inset-0 rounded-xl focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-petrol"
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
											<AuthTypeBadge authType={server.authType} />
											<VisibilityBadge visibility={server.visibility ?? "workspace"} />
										</div>
									</div>
								</div>
								<p className="pointer-events-none mt-3 line-clamp-2 min-h-[38px] flex-1 text-[12.5px] leading-[1.5] text-subtle dark:text-muted-foreground">
									{server.description || "No description provided."}
								</p>
								<p className="pointer-events-none mt-3 truncate border-t border-[#edf2ef] pt-3 font-mono text-[10.5px] text-meta dark:border-white/5 dark:text-panel-dim">
									{server.url}
								</p>
								<div className="relative z-10 mt-3 flex flex-wrap items-center justify-end gap-1.5">
									<RowTestButton server={server} />
									{isAdmin && (
										<>
											<button
												type="button"
												onClick={() => {
													router.push(`/mcp-servers/${server.id}?edit=1`);
												}}
												className="cursor-pointer rounded-[7px] border border-border px-[11px] py-[5px] text-[12px] font-medium text-body transition-colors hover:bg-sidebar dark:text-panel-body dark:hover:bg-white/5"
											>
												Edit
											</button>
											<DropdownMenu
												items={[
													...(server.authType === "oauth2"
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
												]}
											/>
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
						router.push(`/mcp-servers/${server.id}`);
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
						) : scope !== "all" && mcpServers.length > 0 ? (
							"No MCP server matches this visibility filter."
						) : (
							"No MCP servers configured. Add one to get started."
						)
					}
				/>
			)}
		</>
	);
}

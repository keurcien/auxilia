"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Check, X } from "lucide-react";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { MCPServer } from "@/types/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import { AuthTypeBadge } from "./auth-type-badge";
import { ServerIconTile } from "./server-icon-tile";
import { useConnectionTest } from "../lib/use-connection-test";

interface MCPServerTableProps {
	search: string;
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
	search,
	onClearSearch,
}: MCPServerTableProps) {
	const router = useRouter();
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
		if (!query) return mcpServers;
		return mcpServers.filter(
			(server) =>
				server.name.toLowerCase().includes(query) ||
				server.url.toLowerCase().includes(query) ||
				(server.description ?? "").toLowerCase().includes(query),
		);
	}, [mcpServers, search]);

	const handleDelete = async (server: MCPServer) => {
		if (
			!window.confirm(`Delete "${server.name}"? Agents lose its tools immediately.`)
		)
			return;
		try {
			await deleteMcpServer(server.id);
		} catch (err: unknown) {
			if (err instanceof Object && "status" in err && err.status === 403) {
				setForbiddenOpen(true);
			} else {
				setActionError(getApiErrorMessage(err, "Failed to delete MCP server."));
			}
		}
	};

	const handleReset = async (server: MCPServer) => {
		if (
			!window.confirm(
				"This will revoke all user connections to this MCP server. Users will need to re-authenticate. Continue?",
			)
		)
			return;
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
			header: "Server",
			width: "minmax(0, 1.35fr)",
			cell: (server) => (
				<div className="flex min-w-0 items-center gap-3">
					<ServerIconTile iconUrl={server.iconUrl} name={server.name} size={32} />
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
			hideBelowMd: true,
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
					<button
						type="button"
						onClick={() => {
							router.push(`/mcp-servers/${server.id}?edit=1`);
						}}
						className="hidden cursor-pointer rounded-[7px] border border-border px-[11px] py-[5px] text-[12px] font-medium text-body transition-colors hover:bg-sidebar md:block dark:text-panel-body dark:hover:bg-white/5"
					>
						Edit
					</button>
					<SageDropdownMenu
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
			{actionError && (
				<div className="mb-3 shrink-0 rounded-[10px] bg-destructive/10 px-4 py-2.5 text-[13px] font-medium text-destructive">
					{actionError}
				</div>
			)}
			<DataTable
				columns={columns}
				rows={filtered}
				rowKey={(server) => server.id}
				isLoading={isLoading}
				scrollBody
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
								className="cursor-pointer font-semibold text-petrol hover:underline"
							>
								Clear search
							</button>
						</span>
					) : (
						"No MCP servers configured. Add one to get started."
					)
				}
			/>
		</>
	);
}

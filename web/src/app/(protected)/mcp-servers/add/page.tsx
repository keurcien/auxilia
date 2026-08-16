"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Loader2, Plus } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { SearchBar } from "@/components/ui/search-bar";
import { Alert } from "@/components/ui/alert";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useUserStore } from "@/stores/user-store";
import { OfficialMCPServer } from "@/types/mcp-servers";
import { AuthTypeBadge } from "../components/auth-type-badge";
import { ServerIconTile } from "../components/server-icon-tile";
import { HeaderButton, SubpageHeader } from "@/components/layout/subpage-header";
import { requiresStaticOAuthCredentials } from "../lib/mcp-server-create-form";

function CatalogCard({
	server,
	isAdded,
	isPending,
	disabled,
	onAdd,
}: {
	server: OfficialMCPServer;
	isAdded: boolean;
	isPending: boolean;
	/** Any add in flight locks every card — prevents duplicate submissions. */
	disabled: boolean;
	onAdd: () => void;
}) {
	return (
		<div className="flex flex-col gap-3 rounded-[14px] border border-border bg-card p-[17px] transition-[border-color,box-shadow] hover:border-input hover:shadow-[0_6px_18px_-4px_rgba(10,25,30,0.08)]">
			<div className="flex min-w-0 items-center gap-3">
				<ServerIconTile iconUrl={server.iconUrl} name={server.name} size={38} />
				<div className="min-w-0 flex-1">
					<div className="flex items-center gap-2">
						<span className="truncate text-[14.5px] font-bold tracking-[-0.01em] text-foreground">
							{server.name}
						</span>
						<AuthTypeBadge
							authType={server.authType}
							className="px-[7px] py-[2px] text-[9px]"
						/>
					</div>
					<div className="mt-0.5 truncate font-mono text-[10px] text-meta dark:text-panel-dim">
						{server.url}
					</div>
				</div>
			</div>
			{/* min-h reserves the full 5 clamped lines (7.5em = 5 × 1.5 line-height)
			    so every card matches the tallest possible description. */}
			<p className="m-0 min-h-[7.5em] flex-1 text-[12.5px] leading-[1.5] text-subtle line-clamp-5 dark:text-panel-body">
				{server.description || "No description provided."}
			</p>
			<div className="flex items-center justify-end">
				{isAdded ? (
					<span className="inline-flex items-center gap-1.5 rounded-[7px] bg-hover px-[13px] py-1.5 text-[12.5px] font-semibold text-meta dark:bg-white/10 dark:text-panel-dim">
						✓ Added
					</span>
				) : (
					<button
						type="button"
						disabled={disabled}
						onClick={onAdd}
						className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-petrol px-[15px] py-1.5 text-[12.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-60"
					>
						{isPending && <Loader2 className="size-3 animate-spin" />}
						{isPending ? "Adding…" : "Add"}
					</button>
				)}
			</div>
		</div>
	);
}

export default function AddMCPServerPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const createMcpServer = useMcpServersStore((state) => state.createMcpServer);

	const [officialServers, setOfficialServers] = useState<OfficialMCPServer[]>(
		[],
	);
	const [isLoading, setIsLoading] = useState(true);
	const [searchQuery, setSearchQuery] = useState("");
	const [addedIds, setAddedIds] = useState<Set<string>>(new Set());
	const [pendingId, setPendingId] = useState<string | null>(null);
	const [submitError, setSubmitError] = useState<string | null>(null);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	useEffect(() => {
		const controller = new AbortController();
		void (async () => {
			try {
				const res = await api.get<OfficialMCPServer[]>("/mcp-servers/official", {
					signal: controller.signal,
				});
				setOfficialServers(res.data);
				setIsLoading(false);
			} catch {
				// Aborted, or the catalog is unavailable — the custom form still works.
				if (!controller.signal.aborted) setIsLoading(false);
			}
		})();
		return () => {
			controller.abort();
		};
	}, []);

	const filtered = useMemo(() => {
		const query = searchQuery.trim().toLowerCase();
		if (!query) return officialServers;
		return officialServers.filter(
			(server) =>
				server.name.toLowerCase().includes(query) ||
				(server.description ?? "").toLowerCase().includes(query),
		);
	}, [officialServers, searchQuery]);

	const handleAdd = async (server: OfficialMCPServer) => {
		if (user && user.role !== "admin") {
			setForbiddenOpen(true);
			return;
		}
		// Entries that need a credential can't be one-click added: non-DCR
		// OAuth servers need a client ID/secret, api_key servers need the key.
		// Collect them in the custom form, pre-filled with the catalog entry.
		if (requiresStaticOAuthCredentials(server) || server.authType === "api_key") {
			router.push(`/mcp-servers/add/custom?official=${server.id}`);
			return;
		}
		setSubmitError(null);
		setPendingId(server.id);
		try {
			await createMcpServer({
				name: server.name,
				url: server.url,
				authType: server.authType,
				description: server.description || undefined,
				iconUrl: server.iconUrl || undefined,
			});
			setAddedIds((prev) => new Set(prev).add(server.id));
		} catch (error: unknown) {
			if (error instanceof Object && "status" in error && error.status === 403) {
				setForbiddenOpen(true);
			} else {
				setSubmitError(getApiErrorMessage(error, "Failed to add MCP server."));
			}
		} finally {
			setPendingId(null);
		}
	};

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			<SubpageHeader
				trail={[
					{ label: "workspace" },
					{ label: "mcp-servers", href: "/mcp-servers" },
					{ label: "add" },
				]}
			>
				<HeaderButton
					onClick={() => {
						router.push("/mcp-servers");
					}}
				>
					Cancel
				</HeaderButton>
			</SubpageHeader>

			<div className="min-h-0 flex-1 overflow-y-auto px-4 py-8 sm:px-9 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				<div className="mx-auto max-w-[1080px]">
					<h1 className="font-display text-[30px] font-bold tracking-[-0.035em] text-foreground">
						Add an MCP server
					</h1>
					<p className="mt-2 max-w-[620px] text-[15px] leading-[1.6] text-body dark:text-panel-body text-pretty">
						Pick a server from the official catalog — endpoint and auth come
						pre-configured — or connect your own.
					</p>

					<SearchBar
						placeholder="Search the catalog…"
						value={searchQuery}
						onChange={setSearchQuery}
						className="mt-6 max-w-[420px]"
					/>

					{submitError && (
						<div className="mt-4">
							<Alert key={submitError} variant="error" message={submitError} />
						</div>
					)}

					{isLoading ? (
						<div className="mt-[22px] grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
							{Array.from({ length: 6 }, (_, i) => (
								<div
									key={i}
									className="h-[150px] animate-pulse rounded-[14px] border border-border bg-hover/50 dark:bg-white/5"
								/>
							))}
						</div>
					) : (
						<>
							{filtered.length > 0 ? (
								<div className="mt-[22px] grid grid-cols-1 gap-3.5 md:grid-cols-2 xl:grid-cols-3">
									{filtered.map((server) => (
										<CatalogCard
											key={server.id}
											server={server}
											isAdded={server.isInstalled || addedIds.has(server.id)}
											isPending={pendingId === server.id}
											disabled={pendingId !== null}
											onAdd={() => {
												void handleAdd(server);
											}}
										/>
									))}
								</div>
							) : (
								<div className="mt-[22px] rounded-[14px] border border-dashed border-input px-5 py-10 text-center text-[14px] font-medium text-faint dark:border-white/15 dark:text-muted-foreground">
									{officialServers.length === 0
										? "The official catalog is unavailable right now."
										: "No catalog servers match your search."}
								</div>
							)}
						</>
					)}

					<Link
						href="/mcp-servers/add/custom"
						className="group mt-[26px] flex items-center gap-3.5 rounded-[14px] border border-dashed border-input px-5 py-[18px] transition-colors hover:border-petrol hover:bg-sidebar dark:border-white/15 dark:hover:bg-white/5"
					>
						<span className="flex size-[38px] shrink-0 items-center justify-center rounded-[10px] bg-petrol-tint text-petrol">
							<Plus className="size-[17px]" />
						</span>
						<span className="min-w-0 flex-1">
							<span className="block text-[14.5px] font-bold tracking-[-0.01em] text-foreground">
								Add a custom server
							</span>
							<span className="mt-0.5 block text-[12.5px] text-subtle dark:text-panel-body">
								Connect any remote MCP endpoint — you configure the address and
								authentication yourself.
							</span>
						</span>
						<ChevronRight className="size-4 text-meta transition-colors group-hover:text-foreground" />
					</Link>
				</div>
			</div>

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="Insufficient privileges"
				message="You need admin permissions to add MCP servers."
			/>
		</div>
	);
}

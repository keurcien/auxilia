"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Image from "next/image";
import { MCPServer } from "@/types/mcp-servers";
import { ToolStatus } from "@/types/agents";
import { ChevronRight } from "lucide-react";
import AgentMCPTool from "./agent-mcp-tool";
import { AgentMCPServerForm } from "../../lib/agent-form";
import { api } from "@/lib/api/client";

interface AgentMCPServerProps {
	/** Saved agent id — undefined in create mode. */
	agentId?: string;
	server: MCPServer;
	binding: AgentMCPServerForm;
	readOnly?: boolean;
	/** Draft update: the complete per-tool map for this server. */
	onToolsChange?: (tools: Record<string, ToolStatus>) => void;
	/**
	 * Draft update: merge freshly fetched tool names into the binding's map.
	 * Applied against the latest state (existing statuses win), so parallel
	 * seeds from sibling servers and in-progress edits never clobber.
	 */
	onSeedTools?: (fetchedNames: string[]) => void;
	/**
	 * A read-mode connect persisted the tool map server-side (sync-tools) —
	 * `tools` is the map the backend saved.
	 */
	onToolsPersisted?: (tools: Record<string, ToolStatus>) => void;
	/** Draft update: detach this server. */
	onRemove?: () => void;
}

interface MCPServerTool {
	name: string;
	description?: string;
}

export default function AgentMCPServer({
	agentId,
	server,
	binding,
	readOnly,
	onToolsChange,
	onSeedTools,
	onToolsPersisted,
	onRemove,
}: AgentMCPServerProps) {
	// Collapsed on page open; not-connected servers auto-expand (effect
	// below) so the Connect action stays visible.
	const [isExpanded, setIsExpanded] = useState(false);
	const [tools, setTools] = useState<MCPServerTool[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [toolsFetched, setToolsFetched] = useState(false);
	const [isConnected, setIsConnected] = useState(false);
	const [isCheckingConnection, setIsCheckingConnection] = useState(true);

	// Auto-expand when not connected
	useEffect(() => {
		if (!isCheckingConnection && !isConnected) {
			setIsExpanded(true);
		}
	}, [isCheckingConnection, isConnected]);

	const handleToggleExpand = () => {
		setIsExpanded(!isExpanded);
	};

	const statusFor = (toolName: string): ToolStatus => {
		// Object.hasOwn (not `in`) so a tool literally named "toString" etc.
		// can't match an inherited prototype member and return a non-status.
		if (binding.tools && Object.hasOwn(binding.tools, toolName)) {
			return binding.tools[toolName];
		}
		return "always_allow";
	};

	// The complete-map rule: the draft's tools map stays null until the user
	// actually edits, then it materializes from the fetched tool list so a
	// Save never sends a partial map (the backend does whole-map replace).
	const materializeTools = useCallback(
		(fetchedTools: MCPServerTool[]): Record<string, ToolStatus> => {
			const full: Record<string, ToolStatus> = Object.fromEntries(
				fetchedTools.map((tool) => [tool.name, "always_allow" as ToolStatus]),
			);
			return { ...full, ...(binding.tools ?? {}) };
		},
		[binding.tools],
	);

	const handleStatusChange = (toolName: string, status: ToolStatus) => {
		if (readOnly) return;
		onToolsChange?.({ ...materializeTools(tools), [toolName]: status });
	};

	// Merge fetched tools into the draft's map whenever a connected server's
	// tools become known, so a Save always persists the complete, current map:
	// null (= never synced) gets seeded, and a stale map gains the server's new
	// tools — the runtime EXCLUDES any tool missing from the saved map, so a
	// draft that lags the server would silently drop tools from the agent.
	// Read mode has no draft to save; the post-connect sync-tools call below
	// covers persistence there.
	const seedFromFetched = useCallback(
		(fetchedTools: MCPServerTool[]) => {
			if (readOnly) return;
			onSeedTools?.(fetchedTools.map((tool) => tool.name));
		},
		[readOnly, onSeedTools],
	);

	// Read mode has no draft, so a saved map that disagrees with the server's
	// live tool list (never synced after an OAuth connect, or a keyless server
	// that gained/lost tools) must be healed server-side: sync-tools merges —
	// curated statuses survive, new tools default to enabled, vanished tools
	// drop. No-op when the map is already current, so merely viewing an
	// up-to-date agent never writes.
	const persistIfStale = useCallback(
		async (fetchedTools: MCPServerTool[]) => {
			if (!readOnly || !agentId) return;
			const existing = binding.tools;
			const upToDate =
				existing !== null &&
				Object.keys(existing).length === fetchedTools.length &&
				fetchedTools.every((tool) => Object.hasOwn(existing, tool.name));
			if (upToDate) return;
			try {
				const res = await api.post(
					`/agents/${agentId}/mcp-servers/${server.id}/sync-tools`,
				);
				const savedTools = res.data.tools as Record<string, ToolStatus> | null;
				if (savedTools) {
					onToolsPersisted?.(savedTools);
				}
			} catch (error) {
				console.error("Failed to sync tools:", error);
			}
		},
		[readOnly, agentId, binding.tools, server.id, onToolsPersisted],
	);

	// Keep `fetchTools` stable (identity keyed only on server.id) so a sibling
	// server's seed re-rendering the parent — which hands us a fresh inline
	// onSeedTools each time — can't churn fetchTools' identity and retrigger the
	// mount effect, restarting an in-flight fetch. The refs track the latest
	// closures so behavior stays current without becoming dependencies.
	const seedRef = useRef(seedFromFetched);
	useEffect(() => {
		seedRef.current = seedFromFetched;
	}, [seedFromFetched]);
	const persistRef = useRef(persistIfStale);
	useEffect(() => {
		persistRef.current = persistIfStale;
	}, [persistIfStale]);

	const fetchTools = useCallback(async () => {
		setIsLoading(true);
		try {
			const res = await api.get(`/mcp-servers/${server.id}/list-tools`);
			const fetchedTools = res.data as MCPServerTool[];
			setTools(fetchedTools);
			setToolsFetched(true);
			seedRef.current(fetchedTools);
			await persistRef.current(fetchedTools);
		} catch (error: unknown) {
			// Check if this is an OAuth authorization required error
			if (
				error &&
				typeof error === "object" &&
				"response" in error &&
				error.response &&
				typeof error.response === "object" &&
				"status" in error.response &&
				error.response.status === 401 &&
				"data" in error.response &&
				error.response.data &&
				typeof error.response.data === "object" &&
				"auth_url" in error.response.data
			) {
				const authUrl = error.response.data.auth_url as string;

				const popup = window.open(authUrl, "_blank", "width=600,height=700");

				const poll = async () => {
					try {
						const statusRes = await api.get(
							`/mcp-servers/${server.id}/is-connected`,
						);
						const statusData = statusRes.data;

						if (statusData.connected) {
							clearInterval(pollInterval);
							setIsConnected(true);

							// Connecting is a deliberate action, so it must land in
							// the config: in edit mode the seed merges the tools into
							// the draft (saved on Save), in read mode sync-tools
							// persists the map server-side immediately.
							const retryRes = await api.get(
								`/mcp-servers/${server.id}/list-tools`,
							);
							const fetchedTools = retryRes.data as MCPServerTool[];
							setTools(fetchedTools);
							setToolsFetched(true);
							setIsLoading(false);
							seedRef.current(fetchedTools);
							await persistRef.current(fetchedTools);

							if (popup && !popup.closed) {
								popup.close();
							}
						}
					} catch (pollError) {
						console.error("Error polling connection status:", pollError);
					}
				};
				const pollInterval = setInterval(() => {
					void poll();
				}, 2000);

				setTimeout(() => {
					clearInterval(pollInterval);
					setIsLoading(false);
				}, 60000);

				return;
			}

			console.error("Failed to fetch tools:", error);
			setTools([]);
		} finally {
			setIsLoading(false);
		}
	}, [server.id]);

	const handleConnect = async () => {
		await fetchTools();
	};

	useEffect(() => {
		setIsCheckingConnection(true);
		api
			.get(`/mcp-servers/${server.id}/is-connected`)
			.then((res) => {
				setIsConnected(res.data.connected);
			})
			.catch((error) => {
				console.error("Failed to check connection status:", error);
				setIsConnected(false);
			})
			.finally(() => {
				setIsCheckingConnection(false);
			});
	}, [server.id]);

	// Fetch tools on initial load if the server is connected
	useEffect(() => {
		if (!toolsFetched && isConnected) {
			fetchTools();
		}
	}, [toolsFetched, isConnected, fetchTools]);

	return (
		<div className="overflow-hidden rounded-[10px] border border-border bg-card">
			<div className="flex items-center gap-2.5 bg-card px-4 py-3">
				<span className="flex size-[26px] shrink-0 items-center justify-center rounded-[6px] border border-border bg-card">
					<Image
						unoptimized
						width={14}
						height={14}
						src={
							server.iconUrl ??
							"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
						}
						alt={server.name}
						className="rounded-[2px] object-contain"
					/>
				</span>
				<span className="truncate text-[13.5px] font-semibold text-foreground">
					{server.name}
				</span>
				{!isCheckingConnection &&
					(isConnected ? (
						<span className="rounded-[4px] bg-success-bg px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em] text-success">
							CONNECTED
						</span>
					) : (
						<span className="rounded-[4px] bg-[#FBEFED] px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em] text-[#B04A3A]">
							NOT CONNECTED
						</span>
					))}
				<button
					onClick={handleToggleExpand}
					aria-label={isExpanded ? "Collapse" : "Expand"}
					className="ml-auto cursor-pointer p-1 text-meta transition-colors hover:text-foreground dark:text-panel-dim"
				>
					<ChevronRight
						className={`size-4 transition-transform ${
							isExpanded ? "rotate-90" : ""
						}`}
					/>
				</button>
			</div>

			{isExpanded && (
				<div className="border-t border-hover dark:border-white/5">
					{!isConnected && !isCheckingConnection ? (
						<div className="p-6 text-center">
							<p className="mb-1 text-[13.5px] font-semibold text-foreground">
								Connect your account
							</p>
							<p className="mb-4 text-xs text-muted-foreground">
								This server requires authentication.
							</p>
							<button
								className="cursor-pointer rounded-[7px] bg-petrol px-4 py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
								onClick={() => {
									void handleConnect();
								}}
							>
								Connect
							</button>
						</div>
					) : isLoading || isCheckingConnection ? (
						<div className="px-4 py-3 text-[13px] text-muted-foreground">
							Loading tools…
						</div>
					) : tools && tools.length > 0 ? (
						// Show ~5-6 tool rows; longer lists scroll within the card.
						<div className="max-h-80 overflow-y-auto [scrollbar-width:thin]">
							{tools.map((tool) => (
								<AgentMCPTool
									key={tool.name}
									toolName={tool.name}
									toolDescription={tool.description}
									status={statusFor(tool.name)}
									readOnly={readOnly}
									onStatusChange={(status) => {
										handleStatusChange(tool.name, status);
									}}
								/>
							))}
						</div>
					) : (
						<div className="px-4 py-3 text-[13px] text-muted-foreground">
							No tools available
						</div>
					)}
					{!readOnly && (
						<div className="flex justify-center border-t border-hover px-4 py-2 dark:border-white/5">
							<button
								className="cursor-pointer rounded-[7px] px-3 py-1.5 text-[12.5px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] dark:hover:bg-[#B04A3A]/10"
								onClick={() => {
									onRemove?.();
								}}
							>
								Disable {server.name}
							</button>
						</div>
					)}
				</div>
			)}
		</div>
	);
}

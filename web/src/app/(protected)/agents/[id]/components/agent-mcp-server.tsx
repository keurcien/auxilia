"use client";

import {
	useState,
	useEffect,
	useCallback,
	useRef,
	type UIEvent,
} from "react";
import {
	MCPServer,
	MCPServerTool,
} from "@/types/mcp-servers";
import { ToolStatus } from "@/types/agents";
import { ChevronRight } from "lucide-react";
import AgentMCPTool from "./agent-mcp-tool";
import MCPToolsDialog from "./mcp-tools-dialog";
import { AgentMCPServerForm } from "../../lib/agent-form";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { ServerIconTile } from "@/app/(protected)/mcp-servers/components/server-icon-tile";
import { useMcpOAuth } from "@/components/providers/mcp-oauth-provider";
import { Switch } from "@/components/ui/switch";
import { ThreeStateToggle } from "@/components/ui/three-state-toggle";

interface AgentMCPServerProps {
	/** Saved agent id — undefined in create mode. */
	agentId?: string;
	server: MCPServer;
	binding: AgentMCPServerForm;
	isExpanded: boolean;
	onExpandedChange: (expanded: boolean) => void;
	readOnly?: boolean;
	canToggleDefault?: boolean;
	mode?: "agent" | "trigger";
	triggerDisabledTools?: string[];
	triggerToolsReadOnly?: boolean;
	/** Whether the viewer may edit this agent at all (default: yes). */
	canEdit?: boolean;
	/** Draft update: the complete per-tool map for this server. */
	onToolsChange?: (tools: Record<string, ToolStatus>) => void;
	/** Draft update: whether new conversations start with this server enabled. */
	onDefaultEnabledChange?: (enabled: boolean) => void;
	onTriggerToolEnabledChange?: (toolName: string, enabled: boolean) => void;
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

const TOOL_RENDER_BATCH_SIZE = 8;

interface ProgressiveToolListProps {
	tools: MCPServerTool[];
	readOnly?: boolean;
	mode: "agent" | "trigger";
	triggerDisabledTools: string[];
	triggerToolsReadOnly: boolean;
	onTriggerToolEnabledChange?: (toolName: string, enabled: boolean) => void;
	statusFor: (toolName: string) => ToolStatus;
	onStatusChange: (toolName: string, status: ToolStatus) => void;
	onAllStatusChange: (status: ToolStatus) => void;
}

function ProgressiveToolList({
	tools,
	readOnly,
	mode,
	triggerDisabledTools,
	triggerToolsReadOnly,
	onTriggerToolEnabledChange,
	statusFor,
	onStatusChange,
	onAllStatusChange,
}: ProgressiveToolListProps) {
	const [visibleToolCount, setVisibleToolCount] = useState(
		TOOL_RENDER_BATCH_SIZE,
	);
	const visibleTools = tools.slice(0, visibleToolCount);
	const remainingToolCount = tools.length - visibleTools.length;
	const firstStatus = tools[0] ? statusFor(tools[0].name) : null;
	const allStatus =
		firstStatus !== null &&
		tools.every((tool) => statusFor(tool.name) === firstStatus)
			? firstStatus
			: null;

	const handleScroll = (event: UIEvent<HTMLDivElement>) => {
		const { scrollTop, clientHeight, scrollHeight } = event.currentTarget;
		if (
			remainingToolCount > 0 &&
			scrollHeight - scrollTop - clientHeight < 80
		) {
			setVisibleToolCount((current) =>
				Math.min(current + TOOL_RENDER_BATCH_SIZE, tools.length),
			);
		}
	};

	return (
		<div
			className="max-h-80 overflow-y-auto [scrollbar-width:thin]"
			onScroll={handleScroll}
		>
			{mode === "agent" && !readOnly && (
				<div className="flex items-center gap-3 border-b border-hover bg-hover/35 px-4 py-2.5 dark:border-white/5 dark:bg-white/[0.025]">
					<div className="min-w-0 flex-1">
						<p className="text-[10.5px] font-semibold tracking-[0.08em] text-label dark:text-muted-foreground">
							ALL TOOLS
						</p>
						<p className="mt-0.5 text-[11.5px] text-muted-foreground">
							Apply one approval policy to every tool
						</p>
					</div>
					<ThreeStateToggle value={allStatus} onChange={onAllStatusChange} />
				</div>
			)}
			{visibleTools.map((tool) => (
				<AgentMCPTool
					key={tool.name}
					toolName={tool.name}
					toolDescription={tool.description ?? undefined}
					status={statusFor(tool.name)}
					readOnly={readOnly}
					mode={mode}
					triggerEnabled={!triggerDisabledTools.includes(tool.name)}
					triggerReadOnly={triggerToolsReadOnly}
					onStatusChange={(status) => {
						onStatusChange(tool.name, status);
					}}
					onTriggerEnabledChange={(enabled) => {
						onTriggerToolEnabledChange?.(tool.name, enabled);
					}}
				/>
			))}
			{remainingToolCount > 0 && (
				<div className="border-t border-hover px-4 py-2 text-center text-[11px] text-meta dark:border-white/5 dark:text-panel-dim">
					{remainingToolCount} more tool
					{remainingToolCount === 1 ? "" : "s"}. Scroll to load
				</div>
			)}
		</div>
	);
}

function DefaultEnabledRow({
	serverName,
	binding,
	readOnly,
	canToggleDefault,
	mode,
	onDefaultEnabledChange,
}: {
	serverName: string;
	binding: AgentMCPServerForm;
	readOnly?: boolean;
	canToggleDefault?: boolean;
	mode: "agent" | "trigger";
	onDefaultEnabledChange?: (enabled: boolean) => void;
}) {
	return (
		<div className="flex items-center gap-3 border-b border-hover bg-petrol-tint/55 px-4 py-3 dark:border-white/5 dark:bg-white/5">
			<div className="min-w-0 flex-1">
				<p className="text-[12.5px] font-semibold text-foreground">
					{mode === "trigger" ? "This trigger" : "New conversations"}
				</p>
				<p className="mt-0.5 text-[11.5px] text-muted-foreground">
					{mode === "trigger"
						? "Allow this MCP server during automated runs"
						: "Enable this MCP server by default"}
				</p>
			</div>
			<Switch
				checked={binding.enabledByDefault ?? true}
				disabled={canToggleDefault === false || (readOnly && !canToggleDefault)}
				onCheckedChange={(checked) => {
					onDefaultEnabledChange?.(checked);
				}}
				aria-label={
					mode === "trigger"
						? `Allow ${serverName} for this trigger`
						: `Enable ${serverName} by default in new conversations`
				}
			/>
		</div>
	);
}

export default function AgentMCPServer({
	agentId,
	server,
	binding,
	isExpanded,
	onExpandedChange,
	readOnly,
	canToggleDefault,
	mode = "agent",
	triggerDisabledTools = [],
	triggerToolsReadOnly = false,
	canEdit = true,
	onToolsChange,
	onDefaultEnabledChange,
	onTriggerToolEnabledChange,
	onSeedTools,
	onToolsPersisted,
	onRemove,
}: AgentMCPServerProps) {
	const { startAuthorization } = useMcpOAuth();
	const [tools, setTools] = useState<MCPServerTool[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [isConnected, setIsConnected] = useState(false);
	const [isCheckingConnection, setIsCheckingConnection] = useState(true);
	const [toolsUnavailable, setToolsUnavailable] = useState(false);
	const [detailsOpen, setDetailsOpen] = useState(false);
	const managedDatabaseUnavailable =
		server.managedBy === "database" &&
		Boolean(server.disabledTools && server.disabledTools.length > 0);

	const handleToggleExpand = () => {
		onExpandedChange(!isExpanded);
	};
	const expandedChangeRef = useRef(onExpandedChange);
	useEffect(() => {
		expandedChangeRef.current = onExpandedChange;
	}, [onExpandedChange]);

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
			if (readOnly || managedDatabaseUnavailable) return;
			onSeedTools?.(fetchedTools.map((tool) => tool.name));
		},
		[readOnly, managedDatabaseUnavailable, onSeedTools],
	);

	// Read mode has no draft, so a saved map that disagrees with the server's
	// live tool list (never synced after an OAuth connect, or a keyless server
	// that gained/lost tools) must be healed server-side: sync-tools merges —
	// curated statuses survive, new tools default to enabled, vanished tools
	// drop. No-op when the map is already current, so merely viewing an
	// up-to-date agent never writes.
	const persistIfStale = useCallback(
		async (fetchedTools: MCPServerTool[]) => {
			// `canEdit` is the permission, `readOnly` only the view mode: a
			// member may view this page but sync-tools writes the agent's tool
			// map, and the API now rejects that below editor. Skipping keeps a
			// viewer from firing a request that can only 403.
			if (
				!readOnly ||
				!agentId ||
				!canEdit ||
				managedDatabaseUnavailable
			)
				return;
			const existing = binding.tools;
			const upToDate =
				existing !== null &&
				Object.keys(existing).length === fetchedTools.length &&
				fetchedTools.every((tool) => Object.hasOwn(existing, tool.name));
			if (upToDate) return;
			try {
				const binding = await mcpServersApi.syncAgentMcpServerTools(
					agentId,
					server.id,
				);
				const savedTools = binding.tools;
				if (savedTools) {
					onToolsPersisted?.(savedTools);
				}
			} catch (error) {
				console.error("Failed to sync tools:", error);
			}
		},
		[
			readOnly,
			canEdit,
			agentId,
			binding.tools,
			server.id,
			managedDatabaseUnavailable,
			onToolsPersisted,
		],
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

	const fetchTools = useCallback(async (oauthPopup?: Window | null) => {
		setIsLoading(true);
		setToolsUnavailable(false);
		try {
			const result = await mcpServersApi.listMcpServerTools(server.id);

			// `auth_required` is an answer, not an error: the server simply is
			// not connected for this user yet, and the backend hands back the
			// URL to open. (This used to arrive as a 401 in the catch below.)
			if (result.status === "auth_required") {
				if (oauthPopup === undefined) {
					setIsConnected(false);
					setToolsUnavailable(true);
					expandedChangeRef.current(true);
					setIsLoading(false);
					return;
				}
				if (
					!startAuthorization({
						authUrl: result.authUrl,
						redirectMode: result.oauthRedirectMode,
						serverId: server.id,
						serverName: server.name,
						popup: oauthPopup,
					})
				) {
					setToolsUnavailable(true);
					setIsLoading(false);
					return;
				}

				// Poll ticks overlap when a response is slow — only the first
				// tick that sees the connection may run the fetch/persist leg,
				// or sync-tools would fire once per in-flight tick.
				let connectHandled = false;
				const poll = async () => {
					try {
						const connected = await mcpServersApi.isMcpServerConnected(
							server.id,
						);

						if (connected && !connectHandled) {
							connectHandled = true;
							clearInterval(pollInterval);

							try {
								// Connecting is a deliberate action, so it must land
								// in the config: in edit mode the seed merges the
								// tools into the draft (saved on Save), in read mode
								// sync-tools persists the map server-side immediately.
								const retry = await mcpServersApi.listMcpServerTools(server.id);
								if (retry.status !== "ok") {
									throw new Error("still not authorized after connect");
								}
								const fetchedTools = retry.tools;
								setTools(fetchedTools);
								setToolsUnavailable(false);
								setIsConnected(true);
								setIsLoading(false);
								seedRef.current(fetchedTools);
								await persistRef.current(fetchedTools);
							} catch (fetchError) {
								console.error(
									"Failed to fetch tools after connect:",
									fetchError,
								);
								// The server IS connected — expose that even though
								// the fetch failed: with toolsFetched still false,
								// the mount effect retries the fetch instead of the
								// card sticking at NOT CONNECTED with polling dead.
								setIsConnected(true);
								setToolsUnavailable(true);
								expandedChangeRef.current(true);
								setIsLoading(false);
							}

							if (oauthPopup && !oauthPopup.closed) {
								oauthPopup.close();
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
				}, result.oauthRedirectMode === "loopback_manual" ? 600000 : 60000);

				return;
			}

			if (oauthPopup && !oauthPopup.closed) oauthPopup.close();
			setTools(result.tools);
			seedRef.current(result.tools);
			await persistRef.current(result.tools);
		} catch (error: unknown) {
			if (oauthPopup && !oauthPopup.closed) oauthPopup.close();
			console.error("Failed to fetch tools:", error);
			setTools([]);
			setToolsUnavailable(true);
			expandedChangeRef.current(true);
		} finally {
			setIsLoading(false);
		}
	}, [server.id, server.name, startAuthorization]);

	const handleConnect = async () => {
		const popup =
			server.authType === "oauth2"
				? window.open("", "_blank", "width=600,height=700")
				: undefined;
		if (server.authType === "oauth2" && !popup) {
			setToolsUnavailable(true);
			return;
		}
		await fetchTools(popup);
	};

	useEffect(() => {
		mcpServersApi
			.isMcpServerConnected(server.id)
			.then((connected) => {
				setIsConnected(connected);
				if (connected) {
					void fetchTools();
				} else {
					expandedChangeRef.current(true);
				}
			})
			.catch((error: unknown) => {
				console.error("Failed to check connection status:", error);
				setIsConnected(false);
				expandedChangeRef.current(true);
			})
			.finally(() => {
				setIsCheckingConnection(false);
			});
	}, [server.id, fetchTools]);

	const disabledTools = new Set(server.disabledTools ?? []);
	const configurableTools = tools.filter(
		(tool) =>
			!disabledTools.has(tool.name) &&
			(mode !== "trigger" || statusFor(tool.name) !== "disabled"),
	);
	const hasTools =
		isConnected &&
		!isLoading &&
		!isCheckingConnection &&
		configurableTools.length > 0;

	return (
		<div
			className={`overflow-hidden rounded-[10px] border border-border bg-card transition-opacity ${
				mode === "trigger" && binding.enabledByDefault === false
					? "opacity-50"
					: ""
			}`}
		>
			<button
				type="button"
				onClick={handleToggleExpand}
				aria-expanded={isExpanded}
				aria-label={isExpanded ? "Collapse" : "Expand"}
				className="flex w-full cursor-pointer items-center gap-2.5 bg-card px-4 py-3 text-left"
			>
				<ServerIconTile
					iconUrl={server.iconUrl}
					serverId={server.id}
					imageRevision={server.imageRevision}
					name={server.name}
					size={26}
				/>
				<span className="truncate text-[13.5px] font-semibold text-foreground">
					{server.name}
				</span>
				<div className="ml-auto flex shrink-0 items-center gap-2">
					{!isCheckingConnection &&
						(toolsUnavailable ? (
							<span className="rounded-[4px] bg-[#FBEFED] px-2 py-0.5 text-[9.5px] font-semibold text-[#B04A3A]">
								Unavailable
							</span>
						) : isConnected ? (
							<span className="rounded-[4px] bg-success-bg px-2 py-0.5 text-[9.5px] font-semibold text-success dark:bg-emerald-950 dark:text-emerald-300">
								Connected
							</span>
						) : (
							<span className="rounded-[4px] bg-[#FBEFED] px-2 py-0.5 text-[9.5px] font-semibold text-[#B04A3A]">
								Not connected
							</span>
						))}
					<ChevronRight
						aria-hidden="true"
						className={`m-1 size-4 text-meta transition-all dark:text-panel-dim ${
							isExpanded ? "rotate-90" : ""
						}`}
					/>
				</div>
			</button>

			{isExpanded && (
				<div className="border-t border-hover dark:border-white/5">
					<DefaultEnabledRow
						serverName={server.name}
						binding={binding}
						readOnly={readOnly}
						canToggleDefault={canToggleDefault}
						mode={mode}
						onDefaultEnabledChange={onDefaultEnabledChange}
					/>
					{mode === "trigger" && binding.enabledByDefault === false ? null : !isConnected &&
					  !isCheckingConnection ? (
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
					) : toolsUnavailable ? (
						<div className="p-6 text-center">
							<p className="mb-1 text-[13.5px] font-semibold text-foreground">
								Server temporarily unavailable
							</p>
							<p className="mb-4 text-xs text-muted-foreground">
								The agent can still respond, but this server&apos;s tools
								will be skipped.
							</p>
							<button
								className="cursor-pointer rounded-[7px] border border-input bg-background px-4 py-2 text-[13px] font-semibold text-foreground transition-colors hover:border-border-hover"
								onClick={() => {
									void fetchTools();
								}}
							>
								Retry
							</button>
						</div>
					) : configurableTools.length > 0 ? (
						<ProgressiveToolList
							tools={configurableTools}
							readOnly={readOnly}
							mode={mode}
							triggerDisabledTools={triggerDisabledTools}
							triggerToolsReadOnly={triggerToolsReadOnly}
							onTriggerToolEnabledChange={onTriggerToolEnabledChange}
							statusFor={statusFor}
							onStatusChange={handleStatusChange}
							onAllStatusChange={(status) => {
								if (readOnly) return;
								const next = materializeTools(tools);
								for (const tool of configurableTools) {
									next[tool.name] = status;
								}
								onToolsChange?.(next);
							}}
						/>
					) : (
						<div className="px-4 py-3 text-[13px] text-muted-foreground">
							No enabled tools available
						</div>
					)}
					{mode === "agent" && (hasTools || !readOnly) && (
						<div
							className={`flex items-center border-t border-hover px-4 py-2 dark:border-white/5 ${
								hasTools ? "justify-between" : "justify-center"
							}`}
						>
							{hasTools && (
								<button
									className="cursor-pointer rounded-[7px] px-3 py-1.5 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
									onClick={() => {
										setDetailsOpen(true);
									}}
								>
									See full descriptions
								</button>
							)}
							{!readOnly && (
								<button
									className="cursor-pointer rounded-[7px] px-3 py-1.5 text-[12.5px] font-semibold text-[#B04A3A] transition-colors hover:bg-[#FBEFED] dark:hover:bg-[#B04A3A]/10"
									onClick={() => {
										onRemove?.();
									}}
								>
									Disable {server.name}
								</button>
							)}
						</div>
					)}
				</div>
			)}

			{hasTools && (
				<MCPToolsDialog
					open={detailsOpen}
					onOpenChange={setDetailsOpen}
					server={server}
					tools={configurableTools}
					statusFor={statusFor}
				/>
			)}
		</div>
	);
}

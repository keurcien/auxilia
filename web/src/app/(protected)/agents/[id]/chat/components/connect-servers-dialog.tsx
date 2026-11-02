"use client";

import Link from "next/link";
import {
	Fragment,
	useState,
	useCallback,
	useEffect,
	useMemo,
	useRef,
} from "react";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
	DialogDescription,
} from "@/components/ui/dialog";
import * as agentsApi from "@/lib/api/resources/agents";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import type { MCPServer } from "@/types/mcp-servers";
import type { AgentResourceMCPServer, AgentResources } from "@/types/agents";
import type {
	ThreadResourceSettings,
	ThreadToolMode,
} from "@/types/threads";
import {
	BoxIcon,
	ExternalLinkIcon,
	GitForkIcon,
	InfoIcon,
	LoaderIcon,
	PlugIcon,
	SearchIcon,
	SparklesIcon,
	XIcon,
} from "lucide-react";
import { toast } from "sonner";
import { ServerIconTile } from "@/app/(protected)/mcp-servers/components/server-icon-tile";
import { useMcpOAuth } from "@/components/providers/mcp-oauth-provider";
import { SkillAvatar } from "@/components/ui/skill-avatar";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { Checkbox } from "@/components/ui/checkbox";
import { SandboxIcon } from "@/components/sandbox-icon";
import { cn } from "@/lib/utils";
import { SANDBOX_PROVIDER_LABELS } from "@/lib/sandbox-providers";
import { useIsMobile } from "@/hooks/use-mobile";

interface ConnectServersDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agentId: string;
	disconnectedServers: MCPServer[];
	onConnectionChange: () => void;
	toolMode: ThreadToolMode | null;
	resourceSettings: ThreadResourceSettings;
	onResourceSettingsChange: (settings: ThreadResourceSettings) => void;
	resourceSettingsSaving?: boolean;
}

type ResourceTab = "servers" | "skills" | "sandboxes" | "subagents";

export function ConnectServersDialog({
	open,
	onOpenChange,
	agentId,
	disconnectedServers,
	onConnectionChange,
	toolMode,
	resourceSettings,
	onResourceSettingsChange,
	resourceSettingsSaving = false,
}: ConnectServersDialogProps) {
	const { startAuthorization } = useMcpOAuth();
	const [activeTab, setActiveTab] = useState<ResourceTab>("servers");
	const [resources, setResources] = useState<AgentResources | null>(null);
	const [resourcesAgentId, setResourcesAgentId] = useState<string | null>(null);
	const [loadFailedFor, setLoadFailedFor] = useState<string | null>(null);
	const [connectedIds, setConnectedIds] = useState<Set<string>>(new Set());
	const [connectingId, setConnectingId] = useState<string | null>(null);
	const [searchQuery, setSearchQuery] = useState("");
	const isMobile = useIsMobile();
	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const resourceRequestRef = useRef(0);
	const rangeAnchorRef = useRef<Record<ResourceTab, string | null>>({
		servers: null,
		skills: null,
		sandboxes: null,
		subagents: null,
	});

	const disconnectedIds = useMemo(
		() => new Set(disconnectedServers.map((server) => server.id)),
		[disconnectedServers],
	);
	const servers = resources?.mcpServers ?? [];
	const skills = resources?.skills ?? [];
	const sandboxes = resources?.sandboxes ?? [];
	const subagents = resources?.subagents ?? [];
	const orderedServers = useMemo(
		() =>
			[...(resources?.mcpServers ?? [])].sort((left, right) => {
				const leftDisconnected =
					disconnectedIds.has(left.id) && !connectedIds.has(left.id);
				const rightDisconnected =
					disconnectedIds.has(right.id) && !connectedIds.has(right.id);
				return Number(rightDisconnected) - Number(leftDisconnected);
			}),
		[connectedIds, disconnectedIds, resources?.mcpServers],
	);
	const normalizedSearchQuery = searchQuery.trim().toLocaleLowerCase();
	const matchesSearch = (...values: Array<string | null | undefined>) =>
		normalizedSearchQuery.length === 0 ||
		values.some((value) =>
			value?.toLocaleLowerCase().includes(normalizedSearchQuery),
		);
	const filteredServers = orderedServers.filter((server) =>
		matchesSearch(server.name),
	);
	const filteredSkills = skills.filter((skill) =>
		matchesSearch(skill.name, skill.description),
	);
	const filteredSandboxes = sandboxes.filter((sandbox) =>
		matchesSearch(sandbox.name, SANDBOX_PROVIDER_LABELS[sandbox.provider]),
	);
	const filteredSubagents = subagents.filter((subagent) =>
		matchesSearch(subagent.name, subagent.description),
	);
	const activeResourceCount =
		activeTab === "servers"
			? servers.length
			: activeTab === "skills"
				? skills.length
				: activeTab === "sandboxes"
					? sandboxes.length
					: subagents.length;
	const visibleResourceCount =
		activeTab === "servers"
			? filteredServers.length
			: activeTab === "skills"
				? filteredSkills.length
				: activeTab === "sandboxes"
					? filteredSandboxes.length
					: filteredSubagents.length;
	const searchPlaceholder =
		activeTab === "servers"
			? "Search MCP servers…"
			: activeTab === "skills"
				? "Search skills…"
				: activeTab === "sandboxes"
					? "Search sandboxes…"
					: "Search subagents…";
	const disabledServerIds = useMemo(
		() => new Set(resourceSettings.disabledMcpServerIds),
		[resourceSettings.disabledMcpServerIds],
	);
	const disabledSkillIds = useMemo(
		() => new Set(resourceSettings.disabledSkillIds),
		[resourceSettings.disabledSkillIds],
	);
	const disabledSandboxIds = useMemo(
		() => new Set(resourceSettings.disabledSandboxIds),
		[resourceSettings.disabledSandboxIds],
	);
	const disabledSubagentIds = useMemo(
		() => new Set(resourceSettings.disabledSubagentIds),
		[resourceSettings.disabledSubagentIds],
	);
	const enabledServerCount = servers.filter(
		(server) => !disabledServerIds.has(server.id),
	).length;
	const enabledSkillCount = skills.filter(
		(skill) => !disabledSkillIds.has(skill.id),
	).length;
	const enabledSandboxCount = sandboxes.filter(
		(sandbox) => !disabledSandboxIds.has(sandbox.id),
	).length;
	const enabledSubagentCount = subagents.filter(
		(subagent) => !disabledSubagentIds.has(subagent.id),
	).length;
	const allServersEnabled =
		servers.length > 0 &&
		servers.every((server) => !disabledServerIds.has(server.id));
	const someServersEnabled = servers.some(
		(server) => !disabledServerIds.has(server.id),
	);
	const allSkillsEnabled =
		skills.length > 0 &&
		skills.every((skill) => !disabledSkillIds.has(skill.id));
	const someSkillsEnabled = skills.some(
		(skill) => !disabledSkillIds.has(skill.id),
	);
	const allSandboxesEnabled =
		sandboxes.length > 0 &&
		sandboxes.every((sandbox) => !disabledSandboxIds.has(sandbox.id));
	const someSandboxesEnabled = sandboxes.some(
		(sandbox) => !disabledSandboxIds.has(sandbox.id),
	);
	const allSubagentsEnabled =
		subagents.length > 0 &&
		subagents.every((subagent) => !disabledSubagentIds.has(subagent.id));
	const someSubagentsEnabled = subagents.some(
		(subagent) => !disabledSubagentIds.has(subagent.id),
	);
	const isLoadingResources =
		open && resourcesAgentId !== agentId && loadFailedFor !== agentId;
	const modeNotice =
		toolMode === "lazy"
			? {
					label: "Lazy overrides these selections.",
					detail:
						"All attached resources are available, and MCP servers are chosen automatically for each prompt. Changes below are saved for Eager or Precision.",
				}
			: toolMode === "no_tools"
				? {
						label: "No tools overrides these selections.",
						detail:
							"No MCP server, skill, sandbox, or subagent is available. Changes below are saved for another mode.",
					}
				: toolMode === "force_all"
					? {
							label: "Force all overrides these selections.",
							detail:
								"Every attached resource and allowed MCP tool is available. Changes below are saved for Eager or Precision.",
						}
					: null;

	const clearPolling = useCallback(() => {
		if (pollRef.current) clearInterval(pollRef.current);
		if (timeoutRef.current) clearTimeout(timeoutRef.current);
		pollRef.current = null;
		timeoutRef.current = null;
	}, []);

	const handleOpenChange = (nextOpen: boolean) => {
		if (!nextOpen) {
			clearPolling();
			setConnectingId(null);
			setSearchQuery("");
			rangeAnchorRef.current = {
				servers: null,
				skills: null,
				sandboxes: null,
				subagents: null,
			};
		}
		onOpenChange(nextOpen);
	};

	useEffect(() => {
		if (!open) return;
		const requestId = ++resourceRequestRef.current;
		void agentsApi
			.getAgentResources(agentId)
			.then((loadedResources) => {
				if (requestId !== resourceRequestRef.current) return;
				setResources(loadedResources);
				setResourcesAgentId(agentId);
				setLoadFailedFor(null);
			})
			.catch((error: unknown) => {
				if (requestId !== resourceRequestRef.current) return;
				console.error("Failed to load agent resources:", error);
				setResources(null);
				setResourcesAgentId(null);
				setLoadFailedFor(agentId);
			});
		return () => {
			resourceRequestRef.current += 1;
		};
	}, [agentId, open]);

	useEffect(() => clearPolling, [clearPolling]);

	const markConnected = useCallback(
		(serverId: string) => {
			setConnectedIds((previous) => new Set(previous).add(serverId));
			setConnectingId(null);
			onConnectionChange();
		},
		[onConnectionChange],
	);

	const handleConnect = useCallback(
		async (server: AgentResourceMCPServer) => {
			setConnectingId(server.id);
			const popup = window.open("", "_blank", "width=600,height=700");

			try {
				const result = await mcpServersApi.listMcpServerTools(server.id);

				if (result.status === "ok") {
					if (popup && !popup.closed) popup.close();
					markConnected(server.id);
					return;
				}

				if (
					!startAuthorization({
						authUrl: result.authUrl,
						redirectMode: result.oauthRedirectMode,
						serverId: server.id,
						serverName: server.name,
						popup,
						onSuccess: () => {
							clearPolling();
							markConnected(server.id);
						},
					})
				) {
					setConnectingId(null);
					return;
				}

				let connectionHandled = false;
				const poll = async () => {
					try {
						const connected = await mcpServersApi.isMcpServerConnected(
							server.id,
						);
						if (!connected || connectionHandled) return;
						connectionHandled = true;
						clearPolling();
						if (popup && !popup.closed) popup.close();
						markConnected(server.id);
					} catch {
						// A transient probe failure should not stop OAuth polling.
					}
				};
				pollRef.current = setInterval(() => {
					void poll();
				}, 2000);
				timeoutRef.current = setTimeout(() => {
					clearPolling();
					setConnectingId(null);
					toast.error(`Connection to ${server.name} timed out.`);
				}, result.oauthRedirectMode === "loopback_manual" ? 600000 : 60000);
			} catch (error: unknown) {
				if (popup && !popup.closed) popup.close();
				console.error("Failed to connect:", error);
				setConnectingId(null);
				toast.error(`Could not connect ${server.name}.`);
			}
		},
		[clearPolling, markConnected, startAuthorization],
	);

	const setResourceEnabled = (
		type: ResourceTab,
		resourceId: string,
		enabled: boolean,
		shiftKey = false,
	) => {
		const disabledKey =
			type === "servers"
				? "disabledMcpServerIds"
				: type === "skills"
					? "disabledSkillIds"
					: type === "sandboxes"
						? "disabledSandboxIds"
						: "disabledSubagentIds";
		const orderedIds =
			type === "servers"
				? orderedServers
						.filter(
							(server) =>
								!disconnectedIds.has(server.id) || connectedIds.has(server.id),
						)
						.map((server) => server.id)
				: type === "skills"
					? skills.map((skill) => skill.id)
					: type === "sandboxes"
						? sandboxes.map((sandbox) => sandbox.id)
						: subagents.map((subagent) => subagent.id);
		const previousAnchor = rangeAnchorRef.current[type];
		rangeAnchorRef.current[type] = resourceId;
		let targetIds = [resourceId];
		if (shiftKey && previousAnchor) {
			const anchorIndex = orderedIds.indexOf(previousAnchor);
			const targetIndex = orderedIds.indexOf(resourceId);
			if (anchorIndex >= 0 && targetIndex >= 0) {
				const from = Math.min(anchorIndex, targetIndex);
				const to = Math.max(anchorIndex, targetIndex);
				targetIds = orderedIds.slice(from, to + 1);
			}
		}
		const disabledIds = new Set(resourceSettings[disabledKey]);
		for (const id of targetIds) {
			if (enabled) disabledIds.delete(id);
			else disabledIds.add(id);
		}
		onResourceSettingsChange({
			...resourceSettings,
			[disabledKey]: [...disabledIds],
		});
	};

	const setAllResourcesEnabled = (type: ResourceTab, enabled: boolean) => {
		const disabledKey =
			type === "servers"
				? "disabledMcpServerIds"
				: type === "skills"
					? "disabledSkillIds"
					: type === "sandboxes"
						? "disabledSandboxIds"
						: "disabledSubagentIds";
		const resourceIds =
			type === "servers"
				? servers.map((server) => server.id)
				: type === "skills"
					? skills.map((skill) => skill.id)
					: type === "sandboxes"
						? sandboxes.map((sandbox) => sandbox.id)
						: subagents.map((subagent) => subagent.id);
		const disabledIds = new Set(resourceSettings[disabledKey]);
		for (const id of resourceIds) {
			if (enabled) disabledIds.delete(id);
			else disabledIds.add(id);
		}
		rangeAnchorRef.current[type] = null;
		onResourceSettingsChange({
			...resourceSettings,
			[disabledKey]: [...disabledIds],
		});
	};

	return (
		<Dialog open={open} onOpenChange={handleOpenChange}>
			<DialogContent className="h-[calc(100dvh-2rem)] grid-rows-[auto_minmax(0,1fr)] gap-3 overflow-y-hidden! p-4 sm:h-auto sm:max-w-[820px] sm:grid-rows-none sm:gap-4 sm:p-6">
				<DialogHeader>
					<DialogTitle>Conversation resources</DialogTitle>
					<DialogDescription>
						Choose which MCP servers, skills, sandboxes and subagents are
						available in this conversation.
					</DialogDescription>
					{modeNotice && (
						<div className="mt-2 flex items-start gap-2.5 rounded-[9px] border border-petrol/20 bg-petrol/5 px-3 py-2.5 text-left dark:border-panel-terminal/20 dark:bg-panel-terminal/8">
							<InfoIcon className="mt-0.5 size-3.5 shrink-0 text-petrol dark:text-panel-terminal" />
							<p className="text-[11.5px] leading-[1.5] text-subtle dark:text-panel-body">
								<span className="font-semibold text-foreground">
									{modeNotice.label}
								</span>{" "}
								{modeNotice.detail}
							</p>
						</div>
					)}
				</DialogHeader>

				<div className="flex h-full min-h-0 flex-col overflow-hidden rounded-[14px] border border-hairline bg-card shadow-[0_1px_2px_rgba(20,35,38,0.03)] sm:h-[500px] sm:flex-row dark:border-white/8 dark:bg-white/[0.025]">
					<div className="order-2 flex w-full shrink-0 flex-col border-t border-hairline bg-sidebar/70 p-1.5 sm:order-none sm:w-[220px] sm:border-t-0 sm:border-r sm:p-2.5 dark:border-white/8 dark:bg-white/[0.025]">
						<div
							role="tablist"
							aria-label="Agent resource type"
							aria-orientation={isMobile ? "horizontal" : "vertical"}
							className="flex gap-1 sm:flex-col"
						>
							{(
								[
									["servers", "MCP servers", PlugIcon],
									["skills", "Skills", SparklesIcon],
									["sandboxes", "Sandbox", BoxIcon],
									["subagents", "Subagents", GitForkIcon],
								] as const
							).map(([tab, label, Icon]) => {
								const isActive = activeTab === tab;
								const mobileLabel =
									tab === "servers"
										? "MCP"
										: tab === "subagents"
											? "Agents"
											: label;
								const count =
									tab === "servers"
										? `${enabledServerCount}/${servers.length}`
										: tab === "skills"
											? `${enabledSkillCount}/${skills.length}`
											: tab === "sandboxes"
												? `${enabledSandboxCount}/${sandboxes.length}`
												: `${enabledSubagentCount}/${subagents.length}`;
								return (
									<button
										key={tab}
										type="button"
										role="tab"
										aria-selected={isActive}
										aria-controls="conversation-resource-panel"
										onClick={() => {
											setActiveTab(tab);
										}}
										className={cn(
											"group relative flex min-w-0 flex-1 cursor-pointer flex-col items-center gap-1 rounded-[10px] px-1 py-2 text-center whitespace-nowrap transition-[background-color,color,box-shadow] sm:w-full sm:flex-none sm:flex-row sm:gap-2.5 sm:px-2.5 sm:py-2.5 sm:text-left",
											isActive
												? "bg-card text-foreground shadow-[0_1px_4px_rgba(20,35,38,0.09)] ring-1 ring-border/70 dark:bg-white/10 dark:ring-white/10"
												: "text-meta hover:bg-card/70 hover:text-foreground dark:text-panel-dim dark:hover:bg-white/5",
										)}
									>
										<span
											className={cn(
												"flex size-6 shrink-0 items-center justify-center transition-colors sm:size-7",
												isActive
													? "text-petrol dark:text-panel-terminal"
													: "text-meta group-hover:text-foreground dark:text-panel-dim",
											)}
										>
											<Icon className="size-3.5" />
										</span>
										<span className="max-w-full truncate text-[10px] font-semibold sm:hidden">
											{mobileLabel}
										</span>
										<span className="hidden min-w-0 flex-1 truncate text-[12.5px] font-semibold sm:block">
											{label}
										</span>
										{resourcesAgentId === agentId && (
											<span
												className={cn(
													"shrink-0 font-mono text-[8.5px] font-semibold tabular-nums sm:rounded-full sm:px-1.5 sm:py-0.5 sm:text-[9.5px]",
													isActive
														? "text-petrol sm:bg-petrol/10 dark:text-panel-terminal"
														: "text-meta sm:bg-hover dark:text-panel-dim sm:dark:bg-white/5",
												)}
											>
												{count}
											</span>
										)}
									</button>
								);
							})}
						</div>
					</div>

					<div
						id="conversation-resource-panel"
						role="tabpanel"
						className="order-1 flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden p-2.5 sm:order-none sm:p-3"
					>
						{!isLoadingResources && activeResourceCount > 0 && (
							<div className="relative mb-2.5 shrink-0">
								<SearchIcon className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-meta dark:text-panel-dim" />
								<input
									type="text"
									value={searchQuery}
									onChange={(event) => {
										setSearchQuery(event.target.value);
									}}
									onKeyDown={(event) => {
										if (event.key === "Escape" && searchQuery) {
											event.preventDefault();
											event.stopPropagation();
											setSearchQuery("");
										}
									}}
									placeholder={searchPlaceholder}
									aria-label={searchPlaceholder}
									autoComplete="off"
									className="h-9 w-full rounded-[9px] border border-hairline bg-sidebar pr-20 pl-9 text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow,background-color] placeholder:text-meta focus:border-petrol/45 focus:bg-card focus:ring-2 focus:ring-petrol/10 dark:border-white/8 dark:bg-white/5 dark:text-panel-button dark:placeholder:text-panel-dim dark:focus:border-panel-terminal/35 dark:focus:bg-white/[0.07] dark:focus:ring-panel-terminal/10"
								/>
								<div className="absolute top-1/2 right-2 flex -translate-y-1/2 items-center gap-1">
									{normalizedSearchQuery && (
										<span className="font-mono text-[9.5px] font-semibold text-meta tabular-nums dark:text-panel-dim">
											{visibleResourceCount}/{activeResourceCount}
										</span>
									)}
									{searchQuery && (
										<button
											type="button"
											onClick={() => {
												setSearchQuery("");
											}}
											aria-label="Clear resource search"
											className="flex size-6 cursor-pointer items-center justify-center rounded-md text-meta transition-colors hover:bg-hover hover:text-foreground dark:text-panel-dim dark:hover:bg-white/8 dark:hover:text-panel-button"
										>
											<XIcon className="size-3.5" />
										</button>
									)}
								</div>
							</div>
						)}
						<div className="min-h-0 flex-1 overflow-y-auto [scrollbar-width:thin]">
					{isLoadingResources ? (
						<div className="flex min-h-[180px] items-center justify-center gap-2 text-[13px] text-meta dark:text-panel-dim">
							<LoaderIcon className="size-4 animate-spin" />
							Loading resources…
						</div>
					) : activeTab === "servers" ? (
						servers.length > 0 ? (
							filteredServers.length > 0 ? (
							<div className="flex flex-col gap-2">
								<ResourceAllToggle
									checked={
										allServersEnabled
											? true
											: someServersEnabled
												? "indeterminate"
												: false
									}
									disabled={resourceSettingsSaving}
									label="All MCP servers"
									onCheckedChange={(checked) => {
										setAllResourcesEnabled("servers", checked);
									}}
								/>
								{filteredServers.map((server, index) => {
									const isEnabled = !disabledServerIds.has(server.id);
									const isDisconnected =
										disconnectedIds.has(server.id) &&
										!connectedIds.has(server.id);
									const isConnecting = connectingId === server.id;
									const previous = filteredServers.at(index - 1);
									const previousIsDisconnected =
										previous !== undefined &&
										disconnectedIds.has(previous.id) &&
										!connectedIds.has(previous.id);
									const startsConnectedGroup =
										!isDisconnected && previousIsDisconnected;
									return (
										<Fragment key={server.id}>
											{startsConnectedGroup && (
												<div className="flex items-center gap-2 px-1 pt-2">
													<span className="text-[9.5px] font-semibold uppercase tracking-[0.08em] text-meta dark:text-panel-dim">
														Connected
													</span>
													<span className="h-px flex-1 bg-hairline dark:bg-white/8" />
												</div>
											)}
											<div className="flex items-center gap-3 rounded-[10px] border border-hairline bg-sidebar p-3 dark:bg-white/5">
												<ServerIconTile
													iconUrl={server.iconUrl}
													serverId={server.id}
													imageRevision={server.imageRevision}
													name={server.name}
													size={32}
												/>
												<p className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink dark:text-panel-button">
													{server.name}
												</p>
												<div className="ml-auto flex shrink-0 items-center gap-2">
													{!isDisconnected && <ConnectionStatusBadge />}
													{isDisconnected && (
														<button
															type="button"
															disabled={connectingId !== null}
															onClick={() => {
																void handleConnect(server);
															}}
															className="flex h-8 min-w-[82px] cursor-pointer items-center justify-center gap-1.5 rounded-full bg-petrol px-3 text-[11.5px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-55"
														>
															{isConnecting ? (
																<LoaderIcon className="size-3.5 animate-spin" />
															) : (
																<PlugIcon className="size-3.5" />
															)}
															{isConnecting ? "Waiting…" : "Connect"}
														</button>
													)}
													{!isDisconnected && (
														<Checkbox
															checked={isEnabled}
															aria-disabled={resourceSettingsSaving}
															onCheckedChange={(checked, event) => {
																setResourceEnabled(
																	"servers",
																	server.id,
																	checked,
																	event.shiftKey,
																);
															}}
															aria-label={`${isEnabled ? "Disable" : "Enable"} ${server.name} for this conversation`}
														/>
													)}
												</div>
											</div>
										</Fragment>
									);
								})}
							</div>
							) : (
								<SearchEmptyState query={searchQuery} />
							)
						) : (
							<EmptyState
								icon={PlugIcon}
								title="No MCP servers"
								description="This agent has no MCP server enabled."
							/>
						)
					) : activeTab === "skills" ? (
						skills.length > 0 ? (
							filteredSkills.length > 0 ? (
							<div className="flex flex-col gap-2">
								<ResourceAllToggle
									checked={
										allSkillsEnabled
											? true
											: someSkillsEnabled
												? "indeterminate"
												: false
									}
									disabled={resourceSettingsSaving}
									label="All skills"
									onCheckedChange={(checked) => {
										setAllResourcesEnabled("skills", checked);
									}}
								/>
								{filteredSkills.map((skill) => {
									const isEnabled = !disabledSkillIds.has(skill.id);
									return (
										<div
											key={skill.id}
											className="flex items-center gap-3 rounded-[10px] border border-hairline bg-sidebar p-3 dark:bg-white/5"
										>
											<Link
												href={`/skills/${skill.id}`}
												target="_blank"
												rel="noreferrer"
												className="group flex min-w-0 flex-1 items-center gap-3 rounded-md"
											>
												<SkillAvatar
													skillId={skill.id}
													name={skill.name}
													emoji={skill.emoji}
													color={skill.color}
													imageRevision={skill.imageRevision}
													size="sm"
												/>
												<div className="min-w-0 flex-1">
													<p className="truncate text-[13px] font-semibold text-ink dark:text-panel-button">
														{skill.name}
													</p>
													{skill.description && (
														<p className="mt-0.5 truncate text-[11.5px] text-meta dark:text-panel-dim">
															{skill.description}
														</p>
													)}
												</div>
												<ExternalLinkIcon className="size-3.5 shrink-0 text-meta transition-colors group-hover:text-petrol dark:text-panel-dim" />
											</Link>
											<Checkbox
												checked={isEnabled}
												aria-disabled={resourceSettingsSaving}
												onCheckedChange={(checked, event) => {
													setResourceEnabled(
														"skills",
														skill.id,
														checked,
														event.shiftKey,
													);
												}}
												aria-label={`${isEnabled ? "Disable" : "Enable"} ${skill.name} for this conversation`}
											/>
										</div>
									);
								})}
							</div>
							) : (
								<SearchEmptyState query={searchQuery} />
							)
						) : (
							<EmptyState
								icon={SparklesIcon}
								title="No skills"
								description="This agent has no skill enabled."
							/>
						)
					) : activeTab === "sandboxes" ? (
						sandboxes.length > 0 ? (
							filteredSandboxes.length > 0 ? (
							<div className="flex flex-col gap-2">
								<ResourceAllToggle
									checked={
										allSandboxesEnabled
											? true
											: someSandboxesEnabled
												? "indeterminate"
												: false
									}
									disabled={resourceSettingsSaving}
									label="All sandboxes"
									onCheckedChange={(checked) => {
										setAllResourcesEnabled("sandboxes", checked);
									}}
								/>
								{filteredSandboxes.map((sandbox) => {
									const isEnabled = !disabledSandboxIds.has(sandbox.id);
									return (
										<div
											key={sandbox.id}
											className="flex items-center gap-3 rounded-[10px] border border-hairline bg-sidebar p-3 dark:bg-white/5"
										>
											<span className="flex size-8 shrink-0 items-center justify-center rounded-[7px] border border-border bg-card">
												<SandboxIcon
													sandboxId={sandbox.id}
													imageRevision={sandbox.imageRevision}
													provider={sandbox.provider}
													size={17}
												/>
											</span>
											<div className="min-w-0 flex-1">
												<p className="truncate text-[13px] font-semibold text-ink dark:text-panel-button">
													{sandbox.name}
												</p>
												<p className="mt-0.5 truncate text-[11.5px] text-meta dark:text-panel-dim">
													{SANDBOX_PROVIDER_LABELS[sandbox.provider]}
												</p>
											</div>
											<div className="ml-auto flex shrink-0 items-center gap-2">
												<ConnectionStatusBadge />
												<Checkbox
													checked={isEnabled}
													aria-disabled={resourceSettingsSaving}
													onCheckedChange={(checked, event) => {
														setResourceEnabled(
															"sandboxes",
															sandbox.id,
															checked,
															event.shiftKey,
														);
													}}
													aria-label={`${isEnabled ? "Disable" : "Enable"} ${sandbox.name} for this conversation`}
												/>
											</div>
										</div>
									);
								})}
							</div>
							) : (
								<SearchEmptyState query={searchQuery} />
							)
						) : (
							<EmptyState
								icon={BoxIcon}
								title="No sandboxes"
								description="This agent has no sandbox enabled."
							/>
						)
					) : subagents.length > 0 ? (
						filteredSubagents.length > 0 ? (
						<div className="flex flex-col gap-2">
							<ResourceAllToggle
								checked={
									allSubagentsEnabled
										? true
										: someSubagentsEnabled
											? "indeterminate"
											: false
								}
								disabled={resourceSettingsSaving}
								label="All subagents"
								onCheckedChange={(checked) => {
									setAllResourcesEnabled("subagents", checked);
								}}
							/>
							{filteredSubagents.map((subagent) => {
								const isEnabled = !disabledSubagentIds.has(subagent.id);
								return (
									<div
										key={subagent.id}
										className="flex items-center gap-3 rounded-[10px] border border-hairline bg-sidebar p-3 dark:bg-white/5"
									>
										<AgentAvatar
											agentId={subagent.id}
											name={subagent.name}
											emoji={subagent.emoji}
											color={subagent.color}
											imageRevision={subagent.imageRevision}
											size="sm"
										/>
										<div className="min-w-0 flex-1">
											<p className="truncate text-[13px] font-semibold text-ink dark:text-panel-button">
												{subagent.name}
											</p>
											{subagent.description && (
												<p className="mt-0.5 truncate text-[11.5px] text-meta dark:text-panel-dim">
													{subagent.description}
												</p>
											)}
										</div>
										<div className="ml-auto flex shrink-0 items-center gap-2">
											<ConnectionStatusBadge />
											<Checkbox
												checked={isEnabled}
												aria-disabled={resourceSettingsSaving}
												onCheckedChange={(checked, event) => {
													setResourceEnabled(
														"subagents",
														subagent.id,
														checked,
														event.shiftKey,
													);
												}}
												aria-label={`${isEnabled ? "Disable" : "Enable"} ${subagent.name} for this conversation`}
											/>
										</div>
									</div>
								);
							})}
						</div>
						) : (
							<SearchEmptyState query={searchQuery} />
						)
					) : (
						<EmptyState
							icon={GitForkIcon}
							title="No subagents"
							description="This agent has no subagent enabled."
						/>
					)}
					</div>
					</div>
				</div>
			</DialogContent>
		</Dialog>
	);
}

function ResourceAllToggle({
	checked,
	disabled,
	label,
	onCheckedChange,
}: {
	checked: boolean | "indeterminate";
	disabled: boolean;
	label: string;
	onCheckedChange: (checked: boolean) => void;
}) {
	return (
		<div className="flex items-center justify-end gap-2 px-1 pb-1">
			<span className="text-[11.5px] font-semibold text-meta dark:text-panel-dim">
				{label}
			</span>
			<Checkbox
				checked={checked}
				aria-disabled={disabled}
				onCheckedChange={onCheckedChange}
				aria-label={`${checked === true ? "Disable" : "Enable"} ${label.toLowerCase()} for this conversation`}
			/>
		</div>
	);
}

function ConnectionStatusBadge() {
	return (
		<span className="inline-flex shrink-0 items-center gap-1.5 rounded-[4px] bg-success-bg px-2 py-[3px] text-[9.5px] font-semibold text-success dark:bg-emerald-950 dark:text-emerald-300">
			<span className="size-[5px] rounded-full bg-success" />
			Connected
		</span>
	);
}

function SearchEmptyState({ query }: { query: string }) {
	return (
		<div className="flex min-h-[180px] flex-col items-center justify-center px-6 text-center">
			<div className="mb-3 flex size-10 items-center justify-center rounded-full bg-hover text-meta dark:bg-white/5 dark:text-panel-dim">
				<SearchIcon className="size-4" />
			</div>
			<p className="text-[13px] font-semibold text-foreground">No matches</p>
			<p className="mt-1 max-w-[280px] truncate text-[11.5px] text-meta dark:text-panel-dim">
				No resources match “{query.trim()}”.
			</p>
		</div>
	);
}

function EmptyState({
	icon: Icon,
	title,
	description,
}: {
	icon: typeof PlugIcon;
	title: string;
	description: string;
}) {
	return (
		<div className="flex min-h-[180px] flex-col items-center justify-center text-center">
			<div className="mb-3 flex size-10 items-center justify-center rounded-full bg-hover text-meta dark:bg-white/5 dark:text-panel-dim">
				<Icon className="size-4" />
			</div>
			<p className="text-[13px] font-semibold text-foreground">{title}</p>
			<p className="mt-1 text-[11.5px] text-meta dark:text-panel-dim">
				{description}
			</p>
		</div>
	);
}

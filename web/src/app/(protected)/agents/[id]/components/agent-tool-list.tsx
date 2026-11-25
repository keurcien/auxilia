"use client";

import { useState, useEffect, useMemo } from "react";
import { ChevronsUpDown, Plus } from "lucide-react";
import { Tooltip } from "react-tooltip";
import { MCPServer } from "@/types/mcp-servers";
import { ToolStatus } from "@/types/agents";
import { Sandbox } from "@/types/sandboxes";
import AgentMCPServer from "./agent-mcp-server";
import AgentSandbox from "./agent-sandbox";
import AddAgentToolDialog from "./add-agent-tool-dialog";
import ConfirmDialog from "@/components/ui/confirm-dialog";
import { AgentMCPServerForm, AgentSandboxForm } from "../../lib/agent-form";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import * as sandboxesApi from "@/lib/api/resources/sandboxes";
import { matchesQuery } from "@/lib/quick-search";
import { THREE_STATE_TOGGLE_TOOLTIP_ID } from "@/components/ui/three-state-toggle";

interface AgentToolListProps {
	/** Saved agent id — undefined in create mode (`/agents/new`). */
	agentId?: string;
	mcpServers: AgentMCPServerForm[];
	sandboxes: AgentSandboxForm[];
	readOnly?: boolean;
	/** Allow the per-conversation switch while keeping membership/tool editing read-only. */
	canToggleDefault?: boolean;
	mode?: "agent" | "trigger";
	triggerDisabledTools?: Record<string, string[]>;
	triggerToolsReadOnly?: boolean;
	/** Whether the viewer may edit this agent at all (default: yes). */
	canEdit?: boolean;
	/**
	 * Functional updater — applied against the LATEST draft state. Never rebuild
	 * the array from the `mcpServers` prop: several servers can seed their tool
	 * maps concurrently (async `fetchTools`), and a snapshot-based update would
	 * let a late callback clobber a sibling's already-seeded map.
	 */
	onMcpServersChange?: (
		update: (prev: AgentMCPServerForm[]) => AgentMCPServerForm[],
	) => void;
	/** Plain array in/out — sandbox bindings have no async seeding. */
	onSandboxesChange?: (sandboxes: AgentSandboxForm[]) => void;
	onTriggerToolEnabledChange?: (
		serverId: string,
		toolName: string,
		enabled: boolean,
	) => void;
	/**
	 * Names of enabled skills whose scripts need the sandbox. Removing the
	 * sandbox while any exist asks first (design 23d: the skills stay
	 * enabled, their instructions keep applying, the scripts are skipped).
	 */
	scriptSkillNames?: string[];
	/** Controlled "Add tool" dialog, so a sibling section can open it. */
	addDialogOpen?: boolean;
	onAddDialogOpenChange?: (open: boolean) => void;
	/**
	 * A read-mode connect persisted this binding's tool map server-side
	 * (sync-tools) — lets the page refresh its copy of the saved agent.
	 */
	onBindingPersisted?: (
		serverId: string,
		tools: Record<string, ToolStatus>,
	) => void;
	resourceKind?: "all" | "mcp" | "sandbox";
	/** Quick search: only the servers and sandboxes matching it are shown. */
	query?: string;
}

export default function AgentToolList({
	agentId,
	mcpServers,
	sandboxes,
	readOnly,
	canToggleDefault,
	mode = "agent",
	triggerDisabledTools = {},
	triggerToolsReadOnly = false,
	canEdit = true,
	onMcpServersChange,
	onSandboxesChange,
	onTriggerToolEnabledChange,
	onBindingPersisted,
	scriptSkillNames = [],
	addDialogOpen,
	onAddDialogOpenChange,
	resourceKind = "all",
	query = "",
}: AgentToolListProps) {
	const [allMCPServers, setAllMCPServers] = useState<MCPServer[]>([]);
	const [allSandboxes, setAllSandboxes] = useState<Sandbox[]>([]);
	const [expandedServerIds, setExpandedServerIds] = useState<Set<string>>(
		() => new Set(),
	);
	const [internalDialogOpen, setInternalDialogOpen] = useState(false);
	const [dialogResourceKind, setDialogResourceKind] = useState<
		"all" | "mcp" | "sandbox"
	>("all");
	const dialogOpen = addDialogOpen ?? internalDialogOpen;
	const setDialogOpen = (open: boolean) => {
		if (!open) setDialogResourceKind("all");
		setInternalDialogOpen(open);
		onAddDialogOpenChange?.(open);
	};
	const openResourceDialog = (kind: "mcp" | "sandbox") => {
		setDialogResourceKind(kind);
		setDialogOpen(true);
	};
	// The sandbox whose removal is waiting on the skills warning.
	const [sandboxToRemove, setSandboxToRemove] = useState<string | null>(null);

	useEffect(() => {
		mcpServersApi.listMcpServers().then(setAllMCPServers);
		sandboxesApi.listSandboxes().then(setAllSandboxes);
	}, []);

	const enabledServers = useMemo(() => {
		const enabledIds = new Set(mcpServers.map((s) => s.mcpServerId));
		return allMCPServers
			.filter((server) => enabledIds.has(server.id))
			.sort((a, b) => a.name.localeCompare(b.name));
	}, [allMCPServers, mcpServers]);
	const visibleServers = enabledServers.filter((server) =>
		matchesQuery(
			query,
			server.name,
			server.description,
			server.url,
			...Object.keys(
				mcpServers.find((s) => s.mcpServerId === server.id)?.tools ?? {},
			),
		),
	);
	const allServersExpanded =
		visibleServers.length > 0 &&
		visibleServers.every((server) => expandedServerIds.has(server.id));

	const setServerExpanded = (serverId: string, expanded: boolean) => {
		setExpandedServerIds((current) => {
			const next = new Set(current);
			if (expanded) {
				next.add(serverId);
			} else {
				next.delete(serverId);
			}
			return next;
		});
	};

	const enabledSandboxes = useMemo(() => {
		const enabledIds = new Set(sandboxes.map((s) => s.sandboxId));
		return allSandboxes
			.filter((sandbox) => enabledIds.has(sandbox.id))
			.sort((a, b) => a.name.localeCompare(b.name));
	}, [allSandboxes, sandboxes]);
	const visibleSandboxes = enabledSandboxes.filter((sandbox) =>
		matchesQuery(query, sandbox.name, sandbox.description, sandbox.provider),
	);

	const bindingFor = (serverId: string): AgentMCPServerForm =>
		mcpServers.find((s) => s.mcpServerId === serverId) ?? {
			mcpServerId: serverId,
			enabledByDefault: true,
			tools: null,
		};

	const handleToolsChange = (
		serverId: string,
		tools: Record<string, ToolStatus>,
	) => {
		onMcpServersChange?.((prev) =>
			prev.map((s) => (s.mcpServerId === serverId ? { ...s, tools } : s)),
		);
	};

	const handleDefaultEnabledChange = (serverId: string, enabled: boolean) => {
		onMcpServersChange?.((prev) =>
			prev.map((server) =>
				server.mcpServerId === serverId
					? { ...server, enabledByDefault: enabled }
					: server,
			),
		);
	};

	// Merge freshly fetched tool names into a binding's map, evaluated against
	// the latest state so concurrent seeds and in-progress user edits are never
	// clobbered. The fetched list is the key universe (stale keys drop out);
	// existing statuses win, unknown tools default to enabled. This is what
	// keeps the draft honest when a server has gained tools since the last
	// save — the runtime excludes any tool missing from the saved map.
	const handleSeedTools = (serverId: string, fetchedNames: string[]) => {
		onMcpServersChange?.((prev) =>
			prev.map((s) => {
				if (s.mcpServerId !== serverId) return s;
				// A Map lookup, not `s.tools[name]`: a tool named like a
				// prototype member ("toString", …) must never resolve to an
				// inherited value.
				const existing = new Map(Object.entries(s.tools ?? {}));
				// Keep the same object when nothing changed so an unchanged
				// fetch never dirties the form or churns identities.
				const upToDate =
					s.tools !== null &&
					existing.size === fetchedNames.length &&
					fetchedNames.every((name) => existing.has(name));
				if (upToDate) return s;
				const merged: Record<string, ToolStatus> = Object.fromEntries(
					fetchedNames.map((name) => [
						name,
						existing.get(name) ?? ("always_allow" as ToolStatus),
					]),
				);
				return { ...s, tools: merged };
			}),
		);
	};

	const handleRemoveServer = (serverId: string) => {
		onMcpServersChange?.((prev) =>
			prev.filter((s) => s.mcpServerId !== serverId),
		);
	};

	const handleAddServer = (serverId: string) => {
		onMcpServersChange?.((prev) =>
			prev.some((s) => s.mcpServerId === serverId)
				? prev
				: [
						...prev,
						{ mcpServerId: serverId, enabledByDefault: true, tools: null },
					],
		);
	};

	const handleAddSandbox = (sandboxId: string) => {
		// One sandbox per agent: adding replaces any existing binding.
		onSandboxesChange?.([
			{ sandboxId, enabledByDefault: true, tools: null },
		]);
	};

	const handleRemoveSandbox = (sandboxId: string) => {
		onSandboxesChange?.(sandboxes.filter((s) => s.sandboxId !== sandboxId));
	};

	const requestRemoveSandbox = (sandboxId: string) => {
		if (scriptSkillNames.length > 0) {
			setSandboxToRemove(sandboxId);
			return;
		}
		handleRemoveSandbox(sandboxId);
	};

	return (
		<div className="flex min-h-0 flex-col gap-8">
			{resourceKind !== "sandbox" && <section>
				<div className="mb-3 flex min-h-[24px] shrink-0 items-center justify-between">
					<div className="flex items-center gap-2.5">
						<span className="text-[10.5px] font-semibold text-label dark:text-muted-foreground">
							MCP Servers{" "}
							<span className="tracking-normal text-meta dark:text-panel-dim">
								{enabledServers.length}
							</span>
						</span>
						{visibleServers.length > 0 && (
							<>
								<span className="h-3 w-px bg-border" aria-hidden="true" />
								<button
									type="button"
									className="flex cursor-pointer items-center gap-1 text-[11.5px] font-medium text-meta transition-colors hover:text-foreground dark:text-panel-dim dark:hover:text-foreground"
									onClick={() => {
										setExpandedServerIds(
											allServersExpanded
												? new Set()
												: new Set(visibleServers.map((server) => server.id)),
										);
									}}
								>
									<ChevronsUpDown className="size-3" />
									{allServersExpanded ? "Collapse all" : "Expand all"}
								</button>
							</>
						)}
					</div>
					{!readOnly && (
						<button
							type="button"
							className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
							onClick={() => {
								openResourceDialog("mcp");
							}}
						>
							<Plus className="size-3" />
							Add server
						</button>
					)}
				</div>
				{visibleServers.length > 0 ? (
					<div className="flex flex-col gap-2.5">
						{visibleServers.map((server) => (
							<AgentMCPServer
								key={server.id}
								agentId={agentId}
								server={server}
								binding={bindingFor(server.id)}
								isExpanded={expandedServerIds.has(server.id)}
								onExpandedChange={(expanded) => {
									setServerExpanded(server.id, expanded);
								}}
								readOnly={readOnly}
								canToggleDefault={canToggleDefault}
								mode={mode}
								triggerDisabledTools={triggerDisabledTools[server.id] ?? []}
								triggerToolsReadOnly={triggerToolsReadOnly}
								canEdit={canEdit}
								onToolsChange={(tools) => {
									handleToolsChange(server.id, tools);
								}}
								onDefaultEnabledChange={(enabled) => {
									handleDefaultEnabledChange(server.id, enabled);
								}}
								onTriggerToolEnabledChange={(toolName, enabled) => {
									onTriggerToolEnabledChange?.(
										server.id,
										toolName,
										enabled,
									);
								}}
								onSeedTools={(fetchedNames) => {
									handleSeedTools(server.id, fetchedNames);
								}}
								onToolsPersisted={(tools) => {
									onBindingPersisted?.(server.id, tools);
								}}
								onRemove={() => {
									handleRemoveServer(server.id);
								}}
							/>
						))}
					</div>
				) : (
					<div className="rounded-[10px] border border-dashed border-input px-4 py-6 text-center text-[13px] text-meta dark:text-panel-dim">
						{enabledServers.length > 0
							? `No MCP servers match “${query.trim()}”`
							: "No MCP servers enabled"}
					</div>
				)}
			</section>}

			{resourceKind !== "mcp" && <section>
				<div className="mb-3 flex min-h-[24px] shrink-0 items-center justify-between">
					<span className="text-[10.5px] font-semibold text-label dark:text-muted-foreground">
						Sandboxes{" "}
						<span className="tracking-normal text-meta dark:text-panel-dim">
							{enabledSandboxes.length}
						</span>
					</span>
					{!readOnly && enabledSandboxes.length === 0 && (
						<button
							type="button"
							className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80 dark:text-panel-terminal"
							onClick={() => {
								openResourceDialog("sandbox");
							}}
						>
							<Plus className="size-3" />
							Add sandbox
						</button>
					)}
				</div>
				{visibleSandboxes.length > 0 ? (
					<div className="flex flex-col gap-2.5">
						{visibleSandboxes.map((sandbox) => {
							const binding = sandboxes.find(
								(candidate) => candidate.sandboxId === sandbox.id,
							);
							return (
								<AgentSandbox
									key={sandbox.id}
									sandbox={sandbox}
									enabledByDefault={binding?.enabledByDefault ?? true}
									readOnly={readOnly}
									canToggleDefault={canToggleDefault}
									mode={mode}
									onDefaultEnabledChange={(enabled) => {
										onSandboxesChange?.(
											sandboxes.map((candidate) =>
												candidate.sandboxId === sandbox.id
													? { ...candidate, enabledByDefault: enabled }
													: candidate,
											),
										);
									}}
									onRemove={() => {
										requestRemoveSandbox(sandbox.id);
									}}
								/>
							);
						})}
					</div>
				) : (
					<div className="rounded-[10px] border border-dashed border-input px-4 py-6 text-center text-[13px] text-meta dark:text-panel-dim">
						{enabledSandboxes.length > 0
							? `No sandboxes match “${query.trim()}”`
							: "No sandbox enabled"}
					</div>
				)}
			</section>}

			<ConfirmDialog
				open={sandboxToRemove !== null}
				onOpenChange={(open) => {
					if (!open) setSandboxToRemove(null);
				}}
				title="Turn off code execution?"
				description={
					<>
						This leaves {scriptSkillNames.length} enabled skill
						{scriptSkillNames.length === 1 ? "" : "s"} without{" "}
						{scriptSkillNames.length === 1 ? "its" : "their"} scripts:{" "}
						<span className="text-[12px] font-semibold text-petrol dark:text-panel-terminal">
							{scriptSkillNames.join(", ")}
						</span>
						. {scriptSkillNames.length === 1 ? "It stays" : "They stay"}{" "}
						enabled, the instructions keep applying, the scripts are skipped.
					</>
				}
				confirmLabel="Turn off"
				destructive
				onConfirm={() => {
					if (sandboxToRemove) handleRemoveSandbox(sandboxToRemove);
				}}
			/>

			{!readOnly && (
				<AddAgentToolDialog
					open={dialogOpen}
					onOpenChange={setDialogOpen}
					resourceKind={dialogResourceKind}
					attachedServerIds={mcpServers.map((s) => s.mcpServerId)}
					attachedSandboxIds={sandboxes.map((s) => s.sandboxId)}
					sandboxes={allSandboxes}
					onAddServer={handleAddServer}
					onAddSandbox={handleAddSandbox}
				/>
			)}
			<Tooltip
				id={THREE_STATE_TOGGLE_TOOLTIP_ID}
				place="top"
				delayShow={300}
				className="z-50 rounded-lg! bg-ink! px-2! py-1! text-xs! text-white!"
			/>
		</div>
	);
}

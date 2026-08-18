"use client";

import { useState, useEffect, useMemo } from "react";
import { Plus } from "lucide-react";
import { MCPServer } from "@/types/mcp-servers";
import { ToolStatus } from "@/types/agents";
import AgentMCPServer from "./agent-mcp-server";
import AgentCodeExecution from "./agent-code-execution";
import AddAgentToolDialog from "./add-agent-tool-dialog";
import { AgentMCPServerForm } from "../../lib/agent-form";
import { api } from "@/lib/api/client";

interface AgentToolListProps {
	/** Saved agent id — undefined in create mode (`/agents/new`). */
	agentId?: string;
	mcpServers: AgentMCPServerForm[];
	hasCodeInterpreter: boolean;
	readOnly?: boolean;
	/**
	 * Functional updater — applied against the LATEST draft state. Never rebuild
	 * the array from the `mcpServers` prop: several servers can seed their tool
	 * maps concurrently (async `fetchTools`), and a snapshot-based update would
	 * let a late callback clobber a sibling's already-seeded map.
	 */
	onMcpServersChange?: (
		update: (prev: AgentMCPServerForm[]) => AgentMCPServerForm[],
	) => void;
	onHasCodeInterpreterChange?: (enabled: boolean) => void;
	/**
	 * A read-mode connect persisted this binding's tool map server-side
	 * (sync-tools) — lets the page refresh its copy of the saved agent.
	 */
	onBindingPersisted?: (
		serverId: string,
		tools: Record<string, ToolStatus>,
	) => void;
}

export default function AgentToolList({
	agentId,
	mcpServers,
	hasCodeInterpreter,
	readOnly,
	onMcpServersChange,
	onHasCodeInterpreterChange,
	onBindingPersisted,
}: AgentToolListProps) {
	const [allMCPServers, setAllMCPServers] = useState<MCPServer[]>([]);
	const [dialogOpen, setDialogOpen] = useState(false);

	useEffect(() => {
		api.get("/mcp-servers").then((res) => {
			setAllMCPServers(res.data);
		});
	}, []);

	const enabledServers = useMemo(() => {
		const enabledIds = new Set(mcpServers.map((s) => s.mcpServerId));
		return allMCPServers.filter((server) => enabledIds.has(server.id));
	}, [allMCPServers, mcpServers]);

	const bindingFor = (serverId: string): AgentMCPServerForm =>
		mcpServers.find((s) => s.mcpServerId === serverId) ?? {
			mcpServerId: serverId,
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
				const merged: Record<string, ToolStatus> = Object.fromEntries(
					fetchedNames.map((name) => [
						name,
						s.tools?.[name] ?? ("always_allow" as ToolStatus),
					]),
				);
				// Keep the same object when nothing changed so an unchanged
				// fetch never dirties the form or churns identities.
				const same =
					s.tools !== null &&
					Object.keys(s.tools).length === fetchedNames.length &&
					fetchedNames.every((name) => s.tools?.[name] === merged[name]);
				return same ? s : { ...s, tools: merged };
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
				: [...prev, { mcpServerId: serverId, tools: null }],
		);
	};

	const hasTools = hasCodeInterpreter || enabledServers.length > 0;

	return (
		<div className="flex min-h-0 flex-col">
			<div className="mb-3 flex min-h-[24px] shrink-0 items-center justify-between">
				<span className="font-mono text-[10.5px] font-semibold tracking-[0.09em] text-label dark:text-muted-foreground">
					TOOLS{" "}
					<span className="tracking-normal text-meta dark:text-panel-dim">
						{enabledServers.length + (hasCodeInterpreter ? 1 : 0)}
					</span>
				</span>
				{!readOnly && (
					<button
						className="flex cursor-pointer items-center gap-1 text-[12.5px] font-semibold text-petrol transition-opacity hover:opacity-80"
						onClick={() => { setDialogOpen(true); }}
					>
						<Plus className="size-3" />
						Add tool
					</button>
				)}
			</div>
			{hasTools ? (
				<div className="flex flex-col gap-2.5">
					{hasCodeInterpreter && (
						<AgentCodeExecution
							readOnly={readOnly}
							onDisable={() => {
								onHasCodeInterpreterChange?.(false);
							}}
						/>
					)}
					{enabledServers.map((server) => (
						<AgentMCPServer
							key={server.id}
							agentId={agentId}
							server={server}
							binding={bindingFor(server.id)}
							readOnly={readOnly}
							onToolsChange={(tools) => {
								handleToolsChange(server.id, tools);
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
				<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
					No tools enabled
				</div>
			)}

			{!readOnly && (
				<AddAgentToolDialog
					open={dialogOpen}
					onOpenChange={setDialogOpen}
					attachedServerIds={mcpServers.map((s) => s.mcpServerId)}
					hasCodeInterpreter={hasCodeInterpreter}
					onAddServer={handleAddServer}
					onSandboxToggle={(enabled) => {
						onHasCodeInterpreterChange?.(enabled);
					}}
				/>
			)}
		</div>
	);
}

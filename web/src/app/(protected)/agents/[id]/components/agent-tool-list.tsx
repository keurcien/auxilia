"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import { Plus } from "lucide-react";
import { MCPServer } from "@/types/mcp-servers";
import {
	Agent,
	AgentDraft,
	AgentDraftUpdater,
	ToolStatus,
} from "@/types/agents";
import AgentMCPServer from "./agent-mcp-server";
import AgentCodeExecution from "./agent-code-execution";
import AddAgentToolDialog from "./add-agent-tool-dialog";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";

interface AgentToolListProps {
	agent: Agent;
	draft: AgentDraft | null;
	onDraftChange: (update: AgentDraftUpdater) => void;
}

export default function AgentToolList({
	agent,
	draft,
	onDraftChange,
}: AgentToolListProps) {
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const [allMCPServers, setAllMCPServers] = useState<MCPServer[]>([]);
	const [dialogOpen, setDialogOpen] = useState(false);

	const isEditing = draft !== null;

	useEffect(() => {
		api.get("/mcp-servers").then((res) => {
			setAllMCPServers(res.data);
		});
	}, []);

	const refreshAgent = useCallback(() => {
		api.get(`/agents/${agent.id}`).then((res) => {
			updateAgent(agent.id, res.data);
		});
	}, [agent.id, updateAgent]);

	// In edit mode the draft drives what's shown; otherwise the live agent.
	const boundServers = useMemo(
		() =>
			draft
				? draft.mcpServers
				: (agent.mcpServers || []).map((s) => ({
						mcpServerId: s.mcpServerId,
						tools: s.tools,
					})),
		[draft, agent.mcpServers],
	);

	const hasCodeInterpreter = draft
		? draft.hasCodeInterpreter
		: agent.hasCodeInterpreter;

	const enabledServers = useMemo(() => {
		const enabledIds = new Set(boundServers.map((s) => s.mcpServerId));
		return allMCPServers.filter((server) => enabledIds.has(server.id));
	}, [allMCPServers, boundServers]);

	const toolsByServerId = useMemo(
		() =>
			new Map(boundServers.map((s) => [s.mcpServerId, s.tools] as const)),
		[boundServers],
	);

	const handleToolStatusChange = (
		serverId: string,
		toolName: string,
		status: ToolStatus,
	) => {
		onDraftChange((prev) => ({
			...prev,
			mcpServers: prev.mcpServers.map((s) =>
				s.mcpServerId === serverId
					? { ...s, tools: { ...(s.tools || {}), [toolName]: status } }
					: s,
			),
		}));
	};

	const handleDetachServer = (serverId: string) => {
		onDraftChange((prev) => ({
			...prev,
			mcpServers: prev.mcpServers.filter((s) => s.mcpServerId !== serverId),
		}));
	};

	const handleAddServer = (serverId: string) => {
		onDraftChange((prev) =>
			prev.mcpServers.some((s) => s.mcpServerId === serverId)
				? prev
				: {
						...prev,
						mcpServers: [
							...prev.mcpServers,
							{ mcpServerId: serverId, tools: null },
						],
					},
		);
		// Seed the per-tool map from live discovery (best effort — the server
		// may need an OAuth connect first, in which case tools stays null).
		api
			.get(`/mcp-servers/${serverId}/list-tools`)
			.then((res) => {
				const seeded = Object.fromEntries(
					(res.data as { name: string }[]).map((tool) => [
						tool.name,
						"always_allow" as ToolStatus,
					]),
				);
				onDraftChange((prev) => ({
					...prev,
					mcpServers: prev.mcpServers.map((s) =>
						s.mcpServerId === serverId && s.tools === null
							? { ...s, tools: seeded }
							: s,
					),
				}));
			})
			.catch(() => {});
	};

	const handleToolsSynced = (serverId: string, toolNames: string[]) => {
		// sync-tools persisted always_allow defaults server-side; mirror them
		// into the draft so a later Save doesn't overwrite them with null.
		onDraftChange((prev) => ({
			...prev,
			mcpServers: prev.mcpServers.map((s) =>
				s.mcpServerId === serverId && s.tools === null
					? {
							...s,
							tools: Object.fromEntries(
								toolNames.map((name) => [
									name,
									"always_allow" as ToolStatus,
								]),
							),
						}
					: s,
			),
		}));
		refreshAgent();
	};

	const handleSandboxToggle = (checked: boolean) => {
		onDraftChange((prev) => ({ ...prev, hasCodeInterpreter: checked }));
	};

	const hasTools = hasCodeInterpreter || enabledServers.length > 0;

	return (
		<div className="flex flex-col min-h-0">
			<div className="flex items-center justify-between min-h-[34px] mb-2.5 shrink-0">
				<span className="text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em] font-[family-name:var(--font-dm-sans)]">
					Tools
				</span>
				{isEditing && (
					<button
						className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[12.5px] font-semibold text-[#6B7F76] dark:text-muted-foreground cursor-pointer transition-all hover:border-[#A3B5AD]"
						onClick={() => setDialogOpen(true)}
					>
						<Plus className="w-[13px] h-[13px] text-[#8FA89E]" />
						Add tool
					</button>
				)}
			</div>
			<div className="flex-1 overflow-y-auto rounded-[22px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-card min-h-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				{hasTools ? (
					<>
						{hasCodeInterpreter && (
							<AgentCodeExecution
								isEditing={isEditing}
								onDisable={() => handleSandboxToggle(false)}
							/>
						)}
						{enabledServers.map((server) => (
							<AgentMCPServer
								key={server.id}
								agentId={agent.id}
								server={server}
								tools={toolsByServerId.get(server.id) ?? null}
								isEditing={isEditing}
								onToolStatusChange={(toolName, status) =>
									handleToolStatusChange(server.id, toolName, status)
								}
								onDetach={() => handleDetachServer(server.id)}
								onToolsSynced={(toolNames) =>
									handleToolsSynced(server.id, toolNames)
								}
							/>
						))}
					</>
				) : (
					<div className="p-4 font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground text-center">
						No tools enabled
					</div>
				)}
			</div>

			<AddAgentToolDialog
				open={dialogOpen}
				onOpenChange={setDialogOpen}
				boundServerIds={boundServers.map((s) => s.mcpServerId)}
				hasCodeInterpreter={hasCodeInterpreter}
				onAddServer={handleAddServer}
				onSandboxToggle={handleSandboxToggle}
			/>
		</div>
	);
}

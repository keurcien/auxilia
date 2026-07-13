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
	mcpServers: AgentMCPServerForm[];
	hasCodeInterpreter: boolean;
	readOnly?: boolean;
	onMcpServersChange?: (servers: AgentMCPServerForm[]) => void;
	onHasCodeInterpreterChange?: (enabled: boolean) => void;
}

export default function AgentToolList({
	mcpServers,
	hasCodeInterpreter,
	readOnly,
	onMcpServersChange,
	onHasCodeInterpreterChange,
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
		onMcpServersChange?.(
			mcpServers.map((s) =>
				s.mcpServerId === serverId ? { ...s, tools } : s,
			),
		);
	};

	const handleRemoveServer = (serverId: string) => {
		onMcpServersChange?.(
			mcpServers.filter((s) => s.mcpServerId !== serverId),
		);
	};

	const handleAddServer = (serverId: string) => {
		onMcpServersChange?.([
			...mcpServers,
			{ mcpServerId: serverId, tools: null },
		]);
	};

	const hasTools = hasCodeInterpreter || enabledServers.length > 0;

	return (
		<div className="flex flex-col min-h-0">
			<div className="flex items-center justify-between min-h-[34px] mb-2.5 shrink-0">
				<span className="text-[10.5px] font-bold text-[#94a59d] dark:text-muted-foreground uppercase tracking-[0.12em] font-[family-name:var(--font-dm-sans)]">
					Tools
				</span>
				{!readOnly && (
					<button
						className="flex items-center gap-1.5 px-[13px] py-1.5 rounded-[9px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.05)] font-[family-name:var(--font-dm-sans)] text-[12px] font-medium normal-case tracking-normal text-[#1e2d28] dark:text-foreground cursor-pointer transition-colors hover:border-[#A3B5AD]"
						onClick={() => { setDialogOpen(true); }}
					>
						<Plus className="w-3 h-3 text-[#6b7f76] dark:text-muted-foreground" />
						Add tool
					</button>
				)}
			</div>
			<div className="flex-1 overflow-y-auto rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)] min-h-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				{hasTools ? (
					<>
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
								server={server}
								binding={bindingFor(server.id)}
								readOnly={readOnly}
								onToolsChange={(tools) => {
									handleToolsChange(server.id, tools);
								}}
								onRemove={() => {
									handleRemoveServer(server.id);
								}}
							/>
						))}
					</>
				) : (
					<div className="p-4 font-[family-name:var(--font-dm-sans)] text-[14px] text-[#8FA89E] dark:text-muted-foreground text-center">
						No tools enabled
					</div>
				)}
			</div>

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

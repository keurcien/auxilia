"use client";

import { useState, useEffect, useMemo } from "react";
import { Plus } from "lucide-react";
import { MCPServer } from "@/types/mcp-servers";
import { Agent } from "@/types/agents";
import AgentMCPServer from "./agent-mcp-server";
import AgentCodeExecution from "./agent-code-execution";
import AddAgentToolDialog from "./add-agent-tool-dialog";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";

interface AgentToolListProps {
	agent: Agent;
	onSaving?: () => void;
	onSaved?: () => void;
}

export default function AgentToolList({
	agent: initialAgent,
	onSaving,
	onSaved,
}: AgentToolListProps) {
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const [allMCPServers, setAllMCPServers] = useState<MCPServer[]>([]);
	const [agent, setAgent] = useState<Agent>(initialAgent);
	const [dialogOpen, setDialogOpen] = useState(false);

	useEffect(() => {
		api.get("/mcp-servers").then((res) => {
			setAllMCPServers(res.data);
		});
	}, []);

	const refreshAgent = () => {
		api.get(`/agents/${agent.id}`).then((res) => {
			setAgent(res.data);
			updateAgent(agent.id, res.data);
		});
	};

	const enabledServers = useMemo(() => {
		const enabledIds = new Set(agent.mcpServers?.map((s) => s.mcpServerId) || []);
		return allMCPServers.filter((server) => enabledIds.has(server.id));
	}, [allMCPServers, agent.mcpServers]);

	const hasTools = agent.hasCodeInterpreter || enabledServers.length > 0;

	return (
		<div className="flex flex-col min-h-0">
			<div className="flex items-center justify-between min-h-[34px] mb-2.5 shrink-0">
				<span className="text-[10.5px] font-bold text-[#94a59d] dark:text-muted-foreground uppercase tracking-[0.12em] font-[family-name:var(--font-dm-sans)]">
					Tools
				</span>
				<button
					className="flex items-center gap-1.5 px-[13px] py-1.5 rounded-[9px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.05)] font-[family-name:var(--font-dm-sans)] text-[12px] font-medium normal-case tracking-normal text-[#1e2d28] dark:text-foreground cursor-pointer transition-colors hover:border-[#A3B5AD]"
					onClick={() => setDialogOpen(true)}
				>
					<Plus className="w-3 h-3 text-[#6b7f76] dark:text-muted-foreground" />
					Add tool
				</button>
			</div>
			<div className="flex-1 overflow-y-auto rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)] min-h-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				{hasTools ? (
					<>
						{agent.hasCodeInterpreter && (
							<AgentCodeExecution
								agent={agent}
								onUpdate={refreshAgent}
								onSaving={onSaving}
								onSaved={onSaved}
							/>
						)}
						{enabledServers.map((server) => (
							<AgentMCPServer
								key={server.id}
								agent={agent}
								server={server}
								onUpdate={refreshAgent}
								onSaving={onSaving}
								onSaved={onSaved}
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
				agent={agent}
				onServerAdded={refreshAgent}
				onSandboxToggled={refreshAgent}
				onSaving={onSaving}
				onSaved={onSaved}
			/>
		</div>
	);
}

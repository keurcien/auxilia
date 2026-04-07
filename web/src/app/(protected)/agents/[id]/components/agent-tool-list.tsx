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

	const hasTools = agent.sandbox || enabledServers.length > 0;

	return (
		<div className="flex flex-col min-h-0">
			<div className="flex items-center justify-between min-h-[34px] mb-2.5 shrink-0">
				<span className="text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em] font-[family-name:var(--font-dm-sans)]">
					Tools
				</span>
				<button
					className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[12.5px] font-semibold text-[#6B7F76] dark:text-muted-foreground cursor-pointer transition-all hover:border-[#A3B5AD]"
					onClick={() => setDialogOpen(true)}
				>
					<Plus className="w-[13px] h-[13px] text-[#8FA89E]" />
					Add tool
				</button>
			</div>
			<div className="flex-1 overflow-y-auto rounded-[22px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-card min-h-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				{hasTools ? (
					<>
						{agent.sandbox && (
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

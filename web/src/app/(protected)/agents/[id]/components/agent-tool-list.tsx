"use client";

import { useState, useEffect, useMemo } from "react";
import { Plus } from "lucide-react";
import { MCPServer } from "@/types/mcp-servers";
import { Agent } from "@/types/agents";
import { Button } from "@/components/ui/button";
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
			<div className="flex items-center justify-between mb-2 shrink-0">
				<h2 className="text-muted-foreground text-sm leading-5 font-medium">Tools</h2>
				<Button
					variant="ghost"
					size="sm"
					className="cursor-pointer"
					onClick={() => setDialogOpen(true)}
				>
					<Plus className="w-4 h-4 mr-1" />
					Add tool
				</Button>
			</div>
			<div className="flex-1 overflow-y-auto rounded-lg border min-h-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
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
					<div className="p-4 text-sm text-muted-foreground text-center">
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

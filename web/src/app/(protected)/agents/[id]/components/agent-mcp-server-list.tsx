"use client";

import { useState, useEffect, useMemo } from "react";
import { Plus } from "lucide-react";
import { MCPServer } from "@/types/mcp-servers";
import { Agent } from "@/types/agents";
import { Button } from "@/components/ui/button";
import AgentMCPServer from "./agent-mcp-server";
import AddAgentMCPServerDialog from "./add-agent-mcp-server-dialog";
import { api } from "@/lib/api/client";

interface AgentMCPServerListProps {
	agent: Agent;
}

export default function AgentMCPServerList({
	agent: initialAgent,
}: AgentMCPServerListProps) {
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
		});
	};

	const enabledServers = useMemo(() => {
		const enabledIds = new Set(agent.mcpServers?.map((s) => s.id) || []);
		return allMCPServers.filter((server) => enabledIds.has(server.id));
	}, [allMCPServers, agent.mcpServers]);

	return (
		<div className="flex flex-col min-h-0">
			<div className="flex items-center justify-between mb-2 shrink-0">
				<h2 className="text-gray-500 text-sm leading-5 font-medium">Tools</h2>
				<Button
					variant="ghost"
					size="sm"
					className="cursor-pointer"
					onClick={() => setDialogOpen(true)}
				>
					<Plus className="w-4 h-4 mr-1" />
					Add MCP Server
				</Button>
			</div>
			<div className="flex-1 overflow-y-auto rounded-lg border min-h-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
				{enabledServers.length > 0 ? (
					enabledServers.map((server) => (
						<AgentMCPServer
							key={server.id}
							agent={agent}
							server={server}
							onUpdate={refreshAgent}
						/>
					))
				) : (
					<div className="p-4 text-sm text-gray-500 text-center">
						No enabled MCP servers
					</div>
				)}
			</div>

			<AddAgentMCPServerDialog
				open={dialogOpen}
				onOpenChange={setDialogOpen}
				agent={agent}
				onServerAdded={refreshAgent}
			/>
		</div>
	);
}

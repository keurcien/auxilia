"use client";

import { useState, useEffect, useMemo } from "react";
import Image from "next/image";
import { Plus } from "lucide-react";
import { api } from "@/lib/api/client";
import { MCPServer } from "@/types/mcp-servers";
import { Agent } from "@/types/agents";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Card, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";

interface AddAgentMCPServerDialogProps {
	open: boolean;
	onOpenChange: (open: boolean) => void;
	agent: Agent;
	onServerAdded?: () => void;
}

interface AvailableAgentMCPServerCardProps {
	server: MCPServer;
	agentId: string;
	onAdd: () => void;
}

function AvailableAgentMCPServerCard({
	server,
	agentId,
	onAdd,
}: AvailableAgentMCPServerCardProps) {
	const [isAdding, setIsAdding] = useState(false);

	const handleAdd = async () => {
		setIsAdding(true);
		try {
			await api.post(`/agents/${agentId}/mcp-servers/${server.id}`, {});
			onAdd();
		} catch (error) {
			console.error("Failed to add MCP server to agent:", error);
		} finally {
			setIsAdding(false);
		}
	};

	return (
		<Card className="border border-border/60 shadow-none rounded-md overflow-hidden group justify-center py-2 h-[50px]">
			<CardHeader className="gap-0 px-4">
				<div className="flex w-full min-w-0 items-center justify-between">
					<div className="flex w-full min-w-0 items-center gap-3">
						<Image
							src={
								server.iconUrl ??
								"https://storage.googleapis.com/choose-assets/mcp.png"
							}
							alt={server.name}
							width={24}
							height={24}
							className="shrink-0 rounded-md"
						/>

						<div className="min-w-0 flex-1">
							<h3 className="text-sm font-medium truncate">{server.name}</h3>
						</div>

						<Button
							variant="ghost"
							size="icon"
							className="cursor-pointer"
							onClick={handleAdd}
							disabled={isAdding}
						>
							<Plus className="w-4 h-4" />
						</Button>
					</div>
				</div>
			</CardHeader>
		</Card>
	);
}

export default function AddAgentMCPServerDialog({
	open,
	onOpenChange,
	agent,
	onServerAdded,
}: AddAgentMCPServerDialogProps) {
	const [allServers, setAllServers] = useState<MCPServer[]>([]);

	useEffect(() => {
		if (open) {
			api.get("/mcp-servers").then((res) => {
				setAllServers(res.data);
			});
		}
	}, [open]);

	const availableServers = useMemo(() => {
		const enabledIds = new Set(agent.mcpServers?.map((s) => s.id) || []);
		return allServers.filter((server) => !enabledIds.has(server.id));
	}, [allServers, agent.mcpServers]);

	const handleServerAdded = () => {
		onServerAdded?.();
		// Refresh the server list
		api.get("/mcp-servers").then((res) => {
			setAllServers(res.data);
		});
	};

	return (
		<Dialog open={open} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-[600px] max-h-[600px]">
				<DialogHeader>
					<DialogTitle>Add MCP Server</DialogTitle>
				</DialogHeader>
				<div className="py-4 overflow-y-auto">
					{availableServers.length > 0 ? (
						<div className="h-[400px] content-start grid md:grid-cols-2 grid-cols-1 gap-x-2.5 gap-y-2 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							{availableServers.map((server) => (
								<AvailableAgentMCPServerCard
									key={server.id}
									server={server}
									agentId={agent.id}
									onAdd={handleServerAdded}
								/>
							))}
						</div>
					) : (
						<div className="text-center py-8 text-muted-foreground">
							<p className="text-sm">No available MCP servers to add.</p>
							<p className="text-xs mt-1">
								All workspace servers are already enabled for this agent.
							</p>
						</div>
					)}
				</div>
			</DialogContent>
		</Dialog>
	);
}

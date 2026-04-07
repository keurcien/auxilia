"use client";

import { useState } from "react";
import { Agent, ToolStatus } from "@/types/agents";
import { api } from "@/lib/api/client";
import {
	ThreeStateToggle,
	ToggleState,
} from "@/components/ui/three-state-toggle";

interface AgentMCPToolProps {
	agent: Agent;
	serverId: string;
	toolName: string;
	toolDescription?: string;
	onUpdate?: () => void;
	onSaving?: () => void;
	onSaved?: () => void;
}

export default function AgentMCPTool({
	agent,
	serverId,
	toolName,
	toolDescription,
	onUpdate,
	onSaving,
	onSaved,
}: AgentMCPToolProps) {
	const agentServer = agent.mcpServers?.find((s) => s.mcpServerId === serverId);

	const getInitialStatus = (): ToolStatus => {
		if (agentServer?.tools && toolName in agentServer.tools) {
			return agentServer.tools[toolName];
		}
		return "always_allow";
	};

	const [toolStatus, setToolStatus] = useState<ToolStatus>(getInitialStatus);

	const handleStatusChange = async (newStatus: ToggleState) => {
		const previousStatus = toolStatus;
		setToolStatus(newStatus);
		onSaving?.();

		try {
			const toolsUpdate: Record<string, ToolStatus> = {
				[toolName]: newStatus,
			};

			await api.patch(`/agents/${agent.id}/mcp-servers/${serverId}`, {
				tools: toolsUpdate,
			});

			// Notify parent to refresh/update
			onUpdate?.();
			onSaved?.();
		} catch (error) {
			console.error("Failed to update tool status:", error);
			setToolStatus(previousStatus);
			onSaved?.();
		}
	};

	return (
		<div className="flex items-center p-3 bg-[#FAFCFB] rounded-2xl hover:bg-sidebar-hover border-[1.5px] border-[#E0E8E4] dark:border-white/10">
			<div className="w-8 h-8 bg-white rounded-full flex items-center justify-center text-muted-foreground text-xs font-semibold mr-3 shrink-0 border-[1.5px] border-[#E0E8E4] dark:border-white/10">
				{toolName.charAt(0).toUpperCase()}
			</div>

			<div className="flex-1 min-w-0 mr-3">
				<div className="font-(family-name:--font-dm-sans) text-[14px] font-semibold text-[#1E2D28] dark:text-foreground truncate">
					{toolName}
				</div>
				{toolDescription && (
					<div className="text-xs text-muted-foreground line-clamp-2">
						{toolDescription}
					</div>
				)}
			</div>

			<div className="flex items-center shrink-0">
				<ThreeStateToggle value={toolStatus} onChange={handleStatusChange} />
			</div>
		</div>
	);
}

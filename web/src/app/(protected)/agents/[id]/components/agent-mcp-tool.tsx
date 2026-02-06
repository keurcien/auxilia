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
	allTools: Array<{ name: string; description?: string }>;
	onUpdate?: () => void;
	onSaving?: () => void;
	onSaved?: () => void;
}

export default function AgentMCPTool({
	agent,
	serverId,
	toolName,
	toolDescription,
	allTools,
	onUpdate,
	onSaving,
	onSaved,
}: AgentMCPToolProps) {
	const agentServer = agent.mcpServers?.find((s) => s.id === serverId);

	// Get the initial tool status from the tools column
	const getInitialStatus = (): ToolStatus => {
		// First, check the new tools column
		if (agentServer?.tools && toolName in agentServer.tools) {
			return agentServer.tools[toolName];
		}
		// Fall back to the old enabledTools array for backwards compatibility
		const isEnabled =
			agentServer?.enabledTools?.includes(toolName) ||
			agentServer?.enabledTools?.includes("*") ||
			false;
		return isEnabled ? "always_allow" : "disabled";
	};

	const [toolStatus, setToolStatus] = useState<ToolStatus>(getInitialStatus);

	const handleStatusChange = async (newStatus: ToggleState) => {
		const previousStatus = toolStatus;
		setToolStatus(newStatus);
		onSaving?.();

		try {
			// Update the tools column with the new status
			const toolsUpdate: Record<string, ToolStatus> = {
				[toolName]: newStatus,
			};

			// Also update the legacy enabled_tools array for backwards compatibility
			const currentEnabledTools = agentServer?.enabledTools || [];
			const hasWildcard = currentEnabledTools.includes("*");
			const isEnabled = newStatus !== "disabled";

			let updatedTools: string[];

			if (isEnabled) {
				// ENABLING A TOOL (always_allow or needs_approval)
				if (hasWildcard) {
					updatedTools = ["*"];
				} else {
					updatedTools = currentEnabledTools.includes(toolName)
						? currentEnabledTools
						: [...currentEnabledTools, toolName];

					// Optimize: if all tools now enabled, switch back to wildcard
					const allToolNames = allTools.map((t) => t.name);
					if (
						updatedTools.length === allToolNames.length &&
						allToolNames.every((name) => updatedTools.includes(name))
					) {
						updatedTools = ["*"];
					}
				}
			} else {
				// DISABLING A TOOL
				if (hasWildcard) {
					// Expand wildcard to explicit list, then remove this tool
					const allToolNames = allTools.map((t) => t.name);
					updatedTools = allToolNames.filter((name) => name !== toolName);
				} else {
					updatedTools = currentEnabledTools.filter((t) => t !== toolName);
				}
			}

			await api.patch(`/agents/${agent.id}/mcp-servers/${serverId}`, {
				enabled_tools: updatedTools,
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
		<div className="flex items-center p-3 bg-gray-50 rounded hover:bg-gray-100">
			<div className="w-8 h-8 bg-gray-200 rounded flex items-center justify-center text-gray-600 text-xs font-semibold mr-3 shrink-0">
				{toolName.charAt(0).toUpperCase()}
			</div>

			<div className="flex-1 min-w-0 mr-3">
				<div className="text-sm font-medium truncate">{toolName}</div>
				{toolDescription && (
					<div className="text-xs text-gray-500 line-clamp-2">
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

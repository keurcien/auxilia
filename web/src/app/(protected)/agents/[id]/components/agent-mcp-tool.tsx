"use client";

import { useState } from "react";
import { Agent } from "@/types/agents";
import { api } from "@/lib/api/client";

interface AgentMCPToolProps {
	agent: Agent;
	serverId: string;
	toolName: string;
	toolDescription?: string;
	allTools: Array<{ name: string; description?: string }>;
	onUpdate?: () => void;
}

export default function AgentMCPTool({
	agent,
	serverId,
	toolName,
	toolDescription,
	allTools,
	onUpdate,
}: AgentMCPToolProps) {
	const agentServer = agent.mcpServers?.find((s) => s.id === serverId);
	const initialEnabled =
		agentServer?.enabledTools?.includes(toolName) ||
		agentServer?.enabledTools?.includes("*") ||
		false;

	const [isToolEnabled, setIsToolEnabled] = useState(initialEnabled);

	const handleToggleTool = async (isEnabled: boolean) => {
		setIsToolEnabled(isEnabled);

		try {
			const currentEnabledTools = agentServer?.enabledTools || [];
			const hasWildcard = currentEnabledTools.includes("*");

			let updatedTools: string[];

			if (isEnabled) {
				// ENABLING A TOOL
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
			});

			// Notify parent to refresh/update
			onUpdate?.();
		} catch (error) {
			console.error("Failed to toggle tool:", error);
			setIsToolEnabled(!isEnabled);
		}
	};

	return (
		<div className="flex p-3 bg-gray-50 rounded hover:bg-gray-100">
			<div className="w-8 h-8 bg-gray-200 rounded flex items-center justify-center text-gray-600 text-xs font-semibold mr-3">
				{toolName.charAt(0).toUpperCase()}
			</div>

			<div className="flex-1">
				<div className="text-sm font-medium">{toolName}</div>
				{toolDescription && (
					<div className="text-xs text-gray-500 line-clamp-2">
						{toolDescription}
					</div>
				)}
			</div>
			<div className="flex items-center">
				<label className="relative inline-flex items-center cursor-pointer">
					<input
						type="checkbox"
						className="sr-only peer"
						checked={isToolEnabled}
						onChange={(e) => handleToggleTool(e.target.checked)}
					/>
					<div className="w-11 h-6 bg-gray-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-black"></div>
				</label>
			</div>
		</div>
	);
}

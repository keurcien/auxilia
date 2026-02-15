"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";

type McpAppTool = {
	serverName: string;
	toolName: string;
	resourceUri: string;
	serverId: string;
};

export type McpAppToolInfo = {
	resourceUri: string;
	serverId: string;
};

export type McpAppToolsMap = Record<string, Record<string, McpAppToolInfo>>;

export const useMcpAppTools = (agentId: string) => {
	const [mcpAppToolsMap, setMcpAppToolsMap] = useState<McpAppToolsMap>({});
	const [isLoading, setIsLoading] = useState<boolean>(true);

	useEffect(() => {
		if (!agentId) {
			setMcpAppToolsMap({});
			setIsLoading(false);
			return;
		}

		let isMounted = true;

		const fetchMcpAppTools = async () => {
			setIsLoading(true);

			try {
				const response = await api.get<McpAppTool[]>(
					`/agents/${agentId}/mcp-app-tools`,
				);
				if (!isMounted) {
					return;
				}

				const nextMap: McpAppToolsMap = {};
				for (const appTool of response.data) {
					const serverMap = nextMap[appTool.serverName] ?? {};
					serverMap[appTool.toolName] = {
						resourceUri: appTool.resourceUri,
						serverId: appTool.serverId,
					};
					nextMap[appTool.serverName] = serverMap;
				}

				setMcpAppToolsMap(nextMap);
			} catch {
				if (!isMounted) {
					return;
				}
				setMcpAppToolsMap({});
			} finally {
				if (isMounted) {
					setIsLoading(false);
				}
			}
		};

		fetchMcpAppTools();

		return () => {
			isMounted = false;
		};
	}, [agentId]);

	return {
		mcpAppToolsMap,
		isLoading,
	};
};

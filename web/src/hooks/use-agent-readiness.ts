import { useEffect, useMemo } from "react";
import { useAgentConnectionStatus } from "@/hooks/use-agent-connection-status";
import { useMcpServersStore } from "@/stores/mcp-servers-store";

export function useAgentReadiness(agentId: string | undefined) {
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const fetchMcpServers = useMcpServersStore((state) => state.fetchMcpServers);
	const { ready, disconnectedServers, status, refetch } =
		useAgentConnectionStatus(agentId);

	useEffect(() => {
		fetchMcpServers().catch(console.error);
	}, [fetchMcpServers]);

	const disconnectedMcpServers = useMemo(() => {
		if (!disconnectedServers || disconnectedServers.length === 0) return [];
		const set = new Set(disconnectedServers);
		return mcpServers.filter((s) => set.has(s.id));
	}, [mcpServers, disconnectedServers]);

	return { ready, status, disconnectedMcpServers, refetch };
}

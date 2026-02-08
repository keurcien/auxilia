import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api/client";

type AgentReadyStatus = "ready" | "not_configured" | "disconnected" | null;

interface AgentReadyState {
	ready: boolean | null;
	disconnectedServers: string[];
	status: AgentReadyStatus;
	refetch: () => void;
}

export function useAgentConnectionStatus(agentId: string | undefined): AgentReadyState {
	const [ready, setReady] = useState<boolean | null>(null);
	const [disconnectedServers, setDisconnectedServers] = useState<string[]>([]);
	const [status, setStatus] = useState<AgentReadyStatus>(null);

	const refetch = useCallback(async () => {
		if (!agentId) return;
		try {
			const res = await api.get(`/agents/${agentId}/is-ready`);
			setReady(res.data.ready);
			setDisconnectedServers(res.data.disconnectedServers);
			setStatus(res.data.status);
		} catch {
			setReady(false);
			setDisconnectedServers([]);
			setStatus("disconnected");
		}
	}, [agentId]);

	useEffect(() => {
		refetch();
	}, [refetch]);

	return { ready, disconnectedServers, status, refetch };
}

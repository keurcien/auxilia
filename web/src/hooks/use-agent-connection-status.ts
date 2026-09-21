import { useEffect, useState, useCallback } from "react";
import * as agentsApi from "@/lib/api/resources/agents";
import type { AgentReadyStatus as ReadyStatus } from "@/lib/api/resources/agents";

type AgentReadyStatus = ReadyStatus | null;

interface AgentReadyState {
	ready: boolean | null;
	disconnectedServers: string[];
	status: AgentReadyStatus;
	/** Human-readable reason, set with `sandbox_unavailable`. */
	detail: string | null;
	refetch: () => void;
}

export function useAgentConnectionStatus(agentId: string | undefined): AgentReadyState {
	const [ready, setReady] = useState<boolean | null>(null);
	const [disconnectedServers, setDisconnectedServers] = useState<string[]>([]);
	const [status, setStatus] = useState<AgentReadyStatus>(null);
	const [detail, setDetail] = useState<string | null>(null);

	const refetch = useCallback(() => {
		if (!agentId) return;
		agentsApi
			.getAgentReadiness(agentId)
			.then((readiness) => {
				setReady(readiness.ready);
				setDisconnectedServers(readiness.disconnectedServers);
				setStatus(readiness.status);
				setDetail(readiness.detail ?? null);
			})
			.catch(() => {
				setReady(false);
				setDisconnectedServers([]);
				setStatus("disconnected");
				setDetail(null);
			});
	}, [agentId]);

	useEffect(() => {
		refetch();
	}, [refetch]);

	return { ready, disconnectedServers, status, detail, refetch };
}

import { useCallback, useEffect, useRef, useState } from "react";
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
	const [resolvedAgentId, setResolvedAgentId] = useState<string | null>(null);
	const requestIdRef = useRef(0);

	const refetch = useCallback(() => {
		const requestedAgentId = agentId;
		const requestId = ++requestIdRef.current;
		if (!requestedAgentId) return;
		agentsApi
			.getAgentReadiness(requestedAgentId)
			.then((readiness) => {
				if (requestId !== requestIdRef.current) return;
				setReady(readiness.ready);
				setDisconnectedServers(readiness.disconnectedServers);
				setStatus(readiness.status);
				setDetail(readiness.detail ?? null);
				setResolvedAgentId(requestedAgentId);
			})
			.catch(() => {
				if (requestId !== requestIdRef.current) return;
				setReady(false);
				setDisconnectedServers([]);
				setStatus("disconnected");
				setDetail(null);
				setResolvedAgentId(requestedAgentId);
			});
	}, [agentId]);

	useEffect(() => {
		refetch();
		return () => {
			requestIdRef.current += 1;
		};
	}, [refetch]);

	const belongsToCurrentAgent = resolvedAgentId === agentId;
	return {
		ready: belongsToCurrentAgent ? ready : null,
		disconnectedServers: belongsToCurrentAgent ? disconnectedServers : [],
		status: belongsToCurrentAgent ? status : null,
		detail: belongsToCurrentAgent ? detail : null,
		refetch,
	};
}

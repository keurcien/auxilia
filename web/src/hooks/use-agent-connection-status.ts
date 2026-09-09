import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api/client";

type AgentReadyStatus =
	| "ready"
	| "not_configured"
	| "disconnected"
	| "sandbox_unavailable"
	| null;

interface AgentReadyState {
	ready: boolean | null;
	disconnectedServers: string[];
	status: AgentReadyStatus;
	/** Human-readable reason, set with `sandbox_unavailable`. */
	detail: string | null;
	refetch: () => Promise<void>;
}

export function useAgentConnectionStatus(agentId: string | undefined): AgentReadyState {
	const [ready, setReady] = useState<boolean | null>(null);
	const [disconnectedServers, setDisconnectedServers] = useState<string[]>([]);
	const [status, setStatus] = useState<AgentReadyStatus>(null);
	const [detail, setDetail] = useState<string | null>(null);

	const refetch = useCallback(async () => {
		if (!agentId) return;
		try {
			const res = await api.get(`/agents/${agentId}/is-ready`);
			setReady(res.data.ready);
			setDisconnectedServers(res.data.disconnectedServers);
			setStatus(res.data.status);
			setDetail(res.data.detail ?? null);
		} catch {
			setReady(false);
			setDisconnectedServers([]);
			setStatus("disconnected");
			setDetail(null);
		}
	}, [agentId]);

	useEffect(() => {
		// The fetch settles later; state is set in its continuation, not in
		// the effect body.
		void Promise.resolve().then(refetch);
	}, [refetch]);

	return { ready, disconnectedServers, status, detail, refetch };
}

import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api/client";

export type AgentReadyStatus =
	| "ready"
	| "not_configured"
	| "disconnected"
	| "sandbox_unavailable"
	| null;

interface AgentReadyState {
	ready: boolean | null;
	disconnectedServers: string[];
	status: AgentReadyStatus;
	/** Human-readable reason when `status` is "sandbox_unavailable". */
	detail: string | null;
	refetch: () => void;
}

export function useAgentConnectionStatus(agentId: string | undefined): AgentReadyState {
	const [ready, setReady] = useState<boolean | null>(null);
	const [disconnectedServers, setDisconnectedServers] = useState<string[]>([]);
	const [status, setStatus] = useState<AgentReadyStatus>(null);
	const [detail, setDetail] = useState<string | null>(null);
	// Bumped by `refetch`; the effect below re-runs the probe.
	const [version, setVersion] = useState(0);

	useEffect(() => {
		if (!agentId) return;
		let cancelled = false;
		api
			.get(`/agents/${agentId}/is-ready`)
			.then((res) => {
				if (cancelled) return;
				setReady(res.data.ready);
				setDisconnectedServers(res.data.disconnectedServers);
				setStatus(res.data.status);
				setDetail(res.data.detail ?? null);
			})
			.catch(() => {
				if (cancelled) return;
				setReady(false);
				setDisconnectedServers([]);
				setStatus("disconnected");
				setDetail(null);
			});
		return () => {
			cancelled = true;
		};
	}, [agentId, version]);

	const refetch = useCallback(() => {
		setVersion((v) => v + 1);
	}, []);

	return { ready, disconnectedServers, status, detail, refetch };
}

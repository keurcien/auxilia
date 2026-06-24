import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api/client";

type AgentReadyStatus = "ready" | "not_configured" | "disconnected" | null;

interface AgentReadyState {
	ready: boolean | null;
	disconnectedServers: string[];
	status: AgentReadyStatus;
	refetch: () => void;
}

type AgentConnectionSnapshot = Omit<AgentReadyState, "refetch">;

async function loadAgentConnectionStatus(
	agentId: string,
): Promise<AgentConnectionSnapshot> {
	try {
		const res = await api.get(`/agents/${agentId}/is-ready`);
		return {
			ready: res.data.ready,
			disconnectedServers: res.data.disconnectedServers,
			status: res.data.status,
		};
	} catch {
		return {
			ready: false,
			disconnectedServers: [],
			status: "disconnected",
		};
	}
}

export function useAgentConnectionStatus(agentId: string | undefined): AgentReadyState {
	const [ready, setReady] = useState<boolean | null>(null);
	const [disconnectedServers, setDisconnectedServers] = useState<string[]>([]);
	const [status, setStatus] = useState<AgentReadyStatus>(null);

	const applySnapshot = useCallback((snapshot: AgentConnectionSnapshot) => {
		setReady(snapshot.ready);
		setDisconnectedServers(snapshot.disconnectedServers);
		setStatus(snapshot.status);
	}, []);

	const refetch = useCallback(async () => {
		if (!agentId) return;
		const snapshot = await loadAgentConnectionStatus(agentId);
		applySnapshot(snapshot);
	}, [agentId, applySnapshot]);

	useEffect(() => {
		if (!agentId) return;

		let ignore = false;

		loadAgentConnectionStatus(agentId)
			.then((snapshot) => {
				if (ignore) return;
				applySnapshot(snapshot);
			})
			.catch(console.error);

		return () => {
			ignore = true;
		};
	}, [agentId, applySnapshot]);

	return { ready, disconnectedServers, status, refetch };
}

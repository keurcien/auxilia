import { useEffect, useRef, useState, useCallback } from "react";
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
	const mountedRef = useRef(false);
	const requestIdRef = useRef(0);

	const applySnapshot = useCallback((snapshot: AgentConnectionSnapshot) => {
		setReady(snapshot.ready);
		setDisconnectedServers(snapshot.disconnectedServers);
		setStatus(snapshot.status);
	}, []);

	useEffect(() => {
		mountedRef.current = true;

		return () => {
			mountedRef.current = false;
			requestIdRef.current += 1;
		};
	}, []);

	const refetch = useCallback(() => {
		if (!agentId) return;
		const requestId = requestIdRef.current + 1;
		requestIdRef.current = requestId;
		loadAgentConnectionStatus(agentId)
			.then((snapshot) => {
				if (!mountedRef.current || requestId !== requestIdRef.current) return;
				applySnapshot(snapshot);
			})
			.catch(console.error);
	}, [agentId, applySnapshot]);

	useEffect(() => {
		if (!agentId) return;

		const requestId = requestIdRef.current + 1;
		requestIdRef.current = requestId;

		loadAgentConnectionStatus(agentId)
			.then((snapshot) => {
				if (!mountedRef.current || requestId !== requestIdRef.current) return;
				applySnapshot(snapshot);
			})
			.catch(console.error);

		return () => {
			if (requestId === requestIdRef.current) {
				requestIdRef.current += 1;
			}
		};
	}, [agentId, applySnapshot]);

	return { ready, disconnectedServers, status, refetch };
}

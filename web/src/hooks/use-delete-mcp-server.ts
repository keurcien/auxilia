"use client";

import { useState } from "react";
import { api } from "@/lib/api/client";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import type { BoundAgent } from "@/types/agents";
import type { MCPServer } from "@/types/mcp-servers";

interface DeleteGuard {
	server: MCPServer;
	agents: BoundAgent[];
}

/**
 * Shared MCP-server delete flow (table + detail page): a server still bound
 * to agents can't be removed silently — `guard` carries the agents for the
 * ResourceInUseDialog, whose confirm calls `confirmDetachAndDelete`.
 */
export function useDeleteMcpServer({
	onDeleted,
	onError,
	onForbidden,
}: {
	onDeleted?: (server: MCPServer) => void;
	onError?: (error: unknown) => void;
	onForbidden?: () => void;
}) {
	const deleteMcpServer = useMcpServersStore((state) => state.deleteMcpServer);
	const [guard, setGuard] = useState<DeleteGuard | null>(null);

	const requestDelete = async (server: MCPServer): Promise<void> => {
		try {
			const response = await api.get(`/mcp-servers/${server.id}/agents`);
			const agents = response.data as BoundAgent[];
			if (agents.length > 0) {
				setGuard({ server, agents });
				return;
			}
			if (!window.confirm(`Delete "${server.name}"?`)) return;
			await deleteMcpServer(server.id);
			onDeleted?.(server);
		} catch (error: unknown) {
			if (error instanceof Object && "status" in error && error.status === 403) {
				onForbidden?.();
			} else {
				onError?.(error);
			}
		}
	};

	/** Dialog confirm — errors propagate so the dialog shows its own banner. */
	const confirmDetachAndDelete = async () => {
		if (!guard) return;
		await deleteMcpServer(guard.server.id, { detachAgents: true });
		onDeleted?.(guard.server);
	};

	return {
		guard,
		clearGuard: () => {
			setGuard(null);
		},
		requestDelete,
		confirmDetachAndDelete,
	};
}

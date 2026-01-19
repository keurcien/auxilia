"use client";

import { useEffect } from "react";
import { useMcpServersStore } from "@/stores/mcp-servers-store";

export function StoreInitializer() {
	const { fetchMcpServers } = useMcpServersStore();

	useEffect(() => {
		// Initialize MCP servers store on app mount
		fetchMcpServers();
	}, [fetchMcpServers]);

	return null;
}

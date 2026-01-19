"use client";

import { useEffect, useState } from "react";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import MCPServerCard from "./mcp-server-card";

export default function MCPServerList() {
	const { mcpServers, fetchMcpServers, isInitialized } = useMcpServersStore();
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		const loadServers = async () => {
			if (isInitialized) {
				setLoading(false);
				return;
			}

			setLoading(true);
			try {
				await fetchMcpServers();
				setError(null);
			} catch (err) {
				setError(err instanceof Error ? err.message : "An error occurred");
			} finally {
				setLoading(false);
			}
		};

		loadServers();
	}, [fetchMcpServers, isInitialized]);

	if (loading) {
		return (
			<div className="flex items-center justify-center p-12">
				<div className="text-gray-500">Loading MCP servers...</div>
			</div>
		);
	}

	if (error) {
		return (
			<div className="flex items-center justify-center p-12">
				<div className="text-red-500">Error loading servers: {error}</div>
			</div>
		);
	}

	if (mcpServers.length === 0) {
		return (
			<div className="flex items-center justify-center p-12">
				<div className="text-gray-500">
					No MCP servers configured. Click the &quot;Add MCP Server&quot; button
					to get started.
				</div>
			</div>
		);
	}

	return (
		<div className="grid grid-cols-3 gap-x-2.5 gap-y-4 mx-0">
			{mcpServers.map((server) => (
				<MCPServerCard key={server.id} server={server} />
			))}
		</div>
	);
}

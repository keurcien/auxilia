"use client";

import { useEffect, useState } from "react";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { MCPServer } from "@/types/mcp-servers";
import MCPServerCard from "./mcp-server-card";

interface MCPServerListProps {
	onServerClick?: (server: MCPServer) => void;
}

export default function MCPServerList({ onServerClick }: MCPServerListProps) {
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

	if (loading) return null;

	if (error) {
		return (
			<div className="flex items-center justify-center p-12 animate-in fade-in duration-300">
				<div className="text-red-500">Error loading servers: {error}</div>
			</div>
		);
	}

	if (mcpServers.length === 0) {
		return (
			<div className="flex items-center justify-center p-12 border border-border rounded-lg animate-in fade-in duration-300">
				<div className="text-muted-foreground">
					No MCP servers configured. Click the &quot;Add MCP Server&quot; button
					to get started.
				</div>
			</div>
		);
	}

	return (
		<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 animate-in fade-in duration-300">
			{mcpServers.map((server, i) => (
				<div
					key={server.id}
					className="h-full animate-in fade-in slide-in-from-bottom-3 duration-400"
					style={{ animationDelay: `${i * 50}ms`, animationFillMode: "both" }}
				>
					<MCPServerCard
						server={server}
						onClick={() => onServerClick?.(server)}
					/>
				</div>
			))}
		</div>
	);
}

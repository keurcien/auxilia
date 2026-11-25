"use client";

import { useEffect, useState } from "react";
import { UsedByList, agentUsedByItem } from "@/components/editor/used-by-list";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import type { BoundAgent } from "@/types/agents";

/** The agents the server is bound to, among those the viewer can see. */
export function MCPServerUsedBy({ serverId }: { serverId: string }) {
	const [loaded, setLoaded] = useState<{
		serverId: string;
		agents: BoundAgent[];
	} | null>(null);
	const agents = loaded?.serverId === serverId ? loaded.agents : null;

	useEffect(() => {
		let current = true;
		mcpServersApi
			.listMcpServerAgents(serverId)
			.then((next) => {
				if (current) setLoaded({ serverId, agents: next });
			})
			.catch((err: unknown) => {
				console.error("Error fetching the server's agents:", err);
				if (current) setLoaded({ serverId, agents: [] });
			});
		return () => {
			current = false;
		};
	}, [serverId]);

	return (
		<UsedByList
			className="mt-[30px]"
			loading={agents === null}
			items={(agents ?? []).map(agentUsedByItem)}
			emptyText="Not bound to any agent yet. Add it from an agent's MCP section."
		/>
	);
}

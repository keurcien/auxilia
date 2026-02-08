"use client";

import { useState, useEffect } from "react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";
import { api } from "@/lib/api/client";

export default function AgentList() {
	const [agents, setAgents] = useState<Agent[]>([]);

	useEffect(() => {
		api
			.get<Agent[]>("/agents")
			.then((response) => setAgents(response.data))
			.catch(console.error);
	}, []);

	if (agents.length === 0) {
		return (
			<div className="flex items-center justify-center p-12 border border-border rounded-lg">
				<div className="text-muted-foreground">
					No agents configured. Click the &quot;Create an agent&quot; button to
					get started.
				</div>
			</div>
		);
	}

	return (
		<div className="w-full mx-auto">
			<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
				{agents.map((agent) => (
					<AgentCard key={agent.id} agent={agent} />
				))}
			</div>
		</div>
	);
}

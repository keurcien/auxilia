"use client";

import { useState, useEffect } from "react";
import { Agent } from "@/types/agents";
import AgentCard from "@/app/(protected)/agents/components/agent-card";

export default function AgentList() {
	const [agents, setAgents] = useState<Agent[]>([]);

	useEffect(() => {
		fetch("http://localhost:8000/agents")
			.then((response) => response.json())
			.then((data) => {
				setAgents(data);
			});
	}, []);
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

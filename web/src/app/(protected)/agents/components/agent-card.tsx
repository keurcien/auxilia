"use client";

import { useRouter } from "next/navigation";
import { Agent } from "@/types/agents";

interface AgentCardProps {
	agent: Agent;
}

export default function AgentCard({ agent }: AgentCardProps) {
	const router = useRouter();

	const openAgentPage = (agentId: string) => {
		router.push(`/agents/${agentId}`);
	};

	return (
		<div
			className="group flex flex-col p-5 bg-white border border-gray-200 rounded-2xl shadow-sm hover:shadow-md transition-all duration-200 cursor-pointer h-full "
			onClick={() => openAgentPage(agent.id)}
		>
			<div className="flex items-start gap-4 mb-3">
				<div className="flex items-center justify-center shrink-0 w-12 h-12 rounded-2xl bg-gray-100 text-2xl">
					{agent.emoji || "🤖"}
				</div>
				<div className="flex flex-col overflow-hidden">
					<h2 className="text-base font-bold text-gray-900 leading-tight truncate w-full">
						{agent.name}
					</h2>
					<p className="text-sm text-gray-500 truncate w-full">
						@{agent.name.toLowerCase().replace(/\s+/g, "_")}
					</p>
				</div>
			</div>
			<p className="text-sm text-gray-600 line-clamp-2">
				{agent.instructions || "No description provided."}
			</p>
		</div>
	);
}

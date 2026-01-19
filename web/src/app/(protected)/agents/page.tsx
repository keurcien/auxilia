"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import AgentList from "@/app/(protected)/agents/components/agent-list";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";
import { Agent } from "@/types/agents";

export default function AgentsPage() {
	const router = useRouter();
	const addAgent = useAgentsStore((state) => state.addAgent);
	const [isCreating, setIsCreating] = useState(false);

	const handleCreateAgent = async () => {
		setIsCreating(true);
		try {
			const response = await api.post("/agents", {
				name: "New Agent",
				instructions: "",
				emoji: "🤖",
				owner_id: "b4937c31-71ac-45e1-b00a-e633191fa1c4",
			});
			const newAgent: Agent = response.data;
			addAgent(newAgent);
			router.push(`/agents/${newAgent.id}`);
		} catch (error) {
			console.error("Error creating agent:", error);
			alert("Failed to create agent. Please try again.");
		} finally {
			setIsCreating(false);
		}
	};

	return (
		<div className="mx-auto min-h-full w-full max-w-5xl px-4 pb-20 @min-screen-md/layout:px-8 @min-screen-xl/layout:max-w-6xl">
			<div className="flex items-center justify-between my-8">
				<h1 className="text-3xl font-bold text-gray-900">
					Your workspace agents
				</h1>

				<Button
					className="flex items-center gap-2 px-4 py-2 bg-black text-sm font-medium text-white rounded-lg hover:bg-gray-800 transition-colors cursor-pointer"
					onClick={handleCreateAgent}
					disabled={isCreating}
				>
					<Plus className="w-4 h-4" />
					{isCreating ? "Creating..." : "Create an agent"}
				</Button>
			</div>
			<AgentList />
		</div>
	);
}

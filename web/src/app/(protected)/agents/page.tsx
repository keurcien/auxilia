"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import AgentList from "@/app/(protected)/agents/components/agent-list";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";
import { useUserStore } from "@/stores/user-store";
import { Agent } from "@/types/agents";

export default function AgentsPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const addAgent = useAgentsStore((state) => state.addAgent);
	const [isCreating, setIsCreating] = useState(false);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);

	const handleCreateAgent = async () => {
		if (!user) return;
		setIsCreating(true);
		try {
			const response = await api.post("/agents", {
				name: "New Agent",
				instructions: "",
				emoji: "🤖",
				owner_id: user.id,
			});
			const newAgent: Agent = response.data;
			addAgent(newAgent);
			router.push(`/agents/${newAgent.id}`);
		} catch (error: unknown) {
			if (
				error instanceof Object &&
				"status" in error &&
				error.status === 403
			) {
				setErrorDialogOpen(true);
			} else {
				console.error("Error creating agent:", error);
			}
		} finally {
			setIsCreating(false);
		}
	};

	return (
		<div className="mx-auto min-h-full w-full max-w-5xl px-4 pb-20 @min-screen-md/layout:px-8 @min-screen-xl/layout:max-w-6xl">
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You need at least editor permissions to create agents."
			/>
			<div className="flex items-center justify-between my-8">
				<h1 className="font-primary font-extrabold text-2xl md:text-4xl tracking-tighter text-[#2A2F2D] dark:text-white">
					Agents
				</h1>

				<Button
					className="flex items-center gap-2 py-2.5 md:py-5 bg-[#2A2F2D] text-sm md:text-base font-semibold text-white rounded-[14px] hover:bg-[#363D3A] transition-colors cursor-pointer shadow-[0_4px_14px_rgba(118,181,160,0.14)] border-none"
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

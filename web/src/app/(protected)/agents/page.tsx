"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import AgentList from "@/app/(protected)/agents/components/agent-list";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import PageHeaderButton from "@/components/page-header-button";
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

				<PageHeaderButton
					onClick={handleCreateAgent}
					disabled={isCreating}
				>
					{isCreating ? "Creating..." : "Create an agent"}
				</PageHeaderButton>
			</div>
			<AgentList />
		</div>
	);
}

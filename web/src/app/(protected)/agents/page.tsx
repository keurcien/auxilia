"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import AgentList from "@/app/(protected)/agents/components/agent-list";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { Button } from "@/components/ui/button";
import { SearchBar } from "@/components/ui/search-bar";
import { api } from "@/lib/api/client";
import { randomAgentColor } from "@/lib/colors";
import { PageContainer } from "@/components/layout/page-container";
import { useAgentsStore } from "@/stores/agents-store";
import { useUserStore } from "@/stores/user-store";
import { Agent } from "@/types/agents";

export default function AgentsPage() {
	const router = useRouter();
	const user = useUserStore((state) => state.user);
	const addAgent = useAgentsStore((state) => state.addAgent);
	const [isCreating, setIsCreating] = useState(false);
	const [errorDialogOpen, setErrorDialogOpen] = useState(false);
	const [search, setSearch] = useState("");

	const handleCreateAgent = async () => {
		if (!user) return;
		setIsCreating(true);
		try {
			const response = await api.post("/agents", {
				name: "New Agent",
				instructions: "",
				emoji: "🤖",
				color: randomAgentColor(),
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
		<PageContainer>
			<ForbiddenErrorDialog
				open={errorDialogOpen}
				onOpenChange={setErrorDialogOpen}
				title="Insufficient privileges"
				message="You need at least editor permissions to create agents."
			/>
			<div className="flex flex-col gap-5 my-8 sm:flex-row sm:items-start sm:justify-between">
				<div className="min-w-0">
					<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[32px] tracking-[-0.03em] text-[#111111] dark:text-white">
						Agents
					</h1>
					<p className="mt-1.5 font-[family-name:var(--font-dm-sans)] text-[15px] font-medium text-[#6B7F76] dark:text-muted-foreground">
						Everything you can chat with — yours, and what the team shares with
						you.
					</p>
				</div>

				<div className="flex items-center gap-3 shrink-0">
					<SearchBar
						placeholder="Search agents..."
						value={search}
						onChange={setSearch}
						hint="⌘K"
						className="w-full sm:w-72"
					/>
					<Button
						className="flex items-center gap-2 px-6! py-3! h-auto! bg-[#111111] dark:bg-white dark:text-[#111111] text-[14px] font-semibold font-[family-name:var(--font-dm-sans)] text-white rounded-full hover:bg-[#222222] dark:hover:bg-gray-100 transition-all cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] border-none whitespace-nowrap"
						onClick={handleCreateAgent}
						disabled={isCreating}
					>
						<Plus className="w-4 h-4" />
						{isCreating ? "Creating..." : "Create an agent"}
					</Button>
				</div>
			</div>
			<AgentList
				search={search}
				onClearSearch={() => {
					setSearch("");
				}}
				onCreateAgent={handleCreateAgent}
			/>
		</PageContainer>
	);
}

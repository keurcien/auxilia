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
	const [view, setView] = useState<"available" | "all" | "archived">(
		"available",
	);

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
						onClick={() => {
							void handleCreateAgent();
						}}
						disabled={isCreating}
					>
						<Plus className="w-4 h-4" />
						{isCreating ? "Creating..." : "Create an agent"}
					</Button>
				</div>
			</div>
			<div className="mb-6 inline-flex items-center gap-1 rounded-full bg-[#F0F4F2] dark:bg-white/5 p-1">
				{(
					[
						{ key: "available", label: "Available to you" },
						{ key: "all", label: "All" },
						{ key: "archived", label: "Archived" },
					] as const
				).map((tab) => (
					<button
						key={tab.key}
						onClick={() => {
							setView(tab.key);
						}}
						className={`rounded-full px-4 py-1.5 font-[family-name:var(--font-dm-sans)] text-[13.5px] font-semibold cursor-pointer transition-colors ${
							view === tab.key
								? "bg-white dark:bg-white/10 text-[#1E2D28] dark:text-foreground shadow-[0_1px_2px_rgba(30,45,40,0.08)]"
								: "text-[#8FA89E] dark:text-muted-foreground hover:text-[#1E2D28] dark:hover:text-foreground"
						}`}
					>
						{tab.label}
					</button>
				))}
			</div>
			<AgentList
				key={view === "archived" ? "archived" : "active"}
				view={view}
				search={search}
				onClearSearch={() => {
					setSearch("");
				}}
				onCreateAgent={() => {
					void handleCreateAgent();
				}}
			/>
		</PageContainer>
	);
}

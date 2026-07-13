"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { agentPastel } from "@/lib/colors";
import { ShieldCheck, ArrowRight, ArchiveIcon, History, Tag } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentToolList from "../[id]/components/agent-tool-list";
import AgentSubagentList from "../[id]/components/agent-subagent-list";
import AgentEditor from "./agent-editor";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import { SageButton } from "@/components/ui/sage-button";
import { EditorHeader } from "@/components/editor/editor-header";
import { EditorSection } from "@/components/editor/editor-section";
import { MessageResponse } from "@/components/ai-elements/message";
import AgentPermissionsDialog from "./agent-permissions-dialog";
import AgentTagsDialog from "./agent-tags-dialog";
import { fromAgent } from "../lib/agent-form";

interface AgentDetailProps {
	agent: Agent;
}

export default function AgentDetail({ agent }: AgentDetailProps) {
	const router = useRouter();
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const removeAgent = useAgentsStore((state) => state.removeAgent);
	const markAgentArchived = useThreadsStore((state) => state.markAgentArchived);
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";

	const liveAgent = useAgentsStore(
		(state) => state.agents.find((a) => a.id === agent.id) ?? agent,
	);

	const [mode, setMode] = useState<"read" | "edit">("read");
	const [permissionsOpen, setPermissionsOpen] = useState(false);
	const [tagsOpen, setTagsOpen] = useState(false);

	// The server-rendered copy is fresher than whatever the store loaded on
	// layout mount — sync it in so read mode and the edit snapshot match it.
	useEffect(() => {
		updateAgent(agent.id, agent);
	}, [agent, updateAgent]);

	const canManageAgent =
		liveAgent.currentUserPermission === "owner" ||
		liveAgent.currentUserPermission === "admin";

	const canEditAgent =
		canManageAgent || liveAgent.currentUserPermission === "editor";

	const handleDeleteAgent = async () => {
		if (!confirm("Are you sure you want to archive this agent?")) {
			return;
		}

		try {
			await api.delete(`/agents/${agent.id}`);
			removeAgent(agent.id);
			markAgentArchived(agent.id);
			router.push("/agents");
		} catch (error) {
			console.error("Error deleting agent:", error);
			alert("Failed to delete agent. Please try again.");
		}
	};

	// Never let a non-editor land in edit mode (e.g. via a shared ?edit=1 URL).
	if (mode === "edit" && canEditAgent) {
		return (
			<AgentEditor
				agent={liveAgent}
				onSaved={() => {
					setMode("read");
				}}
				onCancel={() => {
					setMode("read");
				}}
			/>
		);
	}

	const form = fromAgent(liveAgent);

	return (
		<div className="h-full flex flex-col font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
			<div className="px-8 py-6 shrink-0 z-10">
				<EditorHeader
					icon={
						<div
							style={{ background: agentPastel(form.color).pill }}
							className="flex items-center justify-center size-full rounded-[13px] text-[23px]"
						>
							{form.emoji}
						</div>
					}
					title={liveAgent.name}
					titlePlaceholder="Agent name"
					subtitle={
						liveAgent.description ? (
							<span className="text-[12.5px] font-medium text-[#94A59D] dark:text-muted-foreground truncate">
								{liveAgent.description}
							</span>
						) : undefined
					}
					actions={
						<>
							{canEditAgent && (
								<SageButton
									color="outline"
									onClick={() => {
										setMode("edit");
									}}
								>
									Edit
								</SageButton>
							)}
							<SageButton
								color="dark"
								onClick={() => { router.push(`/agents/${agent.id}/chat`); }}
							>
								Chat
								<ArrowRight className="size-[15px]" />
							</SageButton>
							<SageDropdownMenu
								items={[
									...(canManageAgent
										? [
											{ label: "View thread history", icon: <History />, onClick: () => { router.push(`/agents/${agent.id}/threads`); } },
											{ label: "Manage permissions", icon: <ShieldCheck />, onClick: () => { setPermissionsOpen(true); } },
										]
										: []),
									...(canEditAgent
										? [
											{ label: "Assign tag", icon: <Tag />, onClick: () => { setTagsOpen(true); } },
											{ separator: true as const },
										]
										: []),
									{ label: "Archive agent", icon: <ArchiveIcon />, destructive: true, onClick: () => { void handleDeleteAgent(); } },
								]}
							/>
						</>
					}
				/>
			</div>

			{/* Two column layout (read-only) */}
			<div className="relative flex flex-col md:flex-row flex-1 min-h-0 px-8 gap-8">
				{/* Left: Description + Instructions */}
				<div className="h-full w-full md:flex-1 flex flex-col min-w-0">
					<EditorSection label="Description" className="shrink-0 mb-7">
						<div className="w-full px-[17px] py-[15px] rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)]">
							<p className="text-[13.5px] font-medium text-[#1E2D28] dark:text-white leading-[1.5]">
								{liveAgent.description || (
									<span className="text-[#A3B5AD] dark:text-white/30">
										No description
									</span>
								)}
							</p>
						</div>
					</EditorSection>

					<EditorSection label="Instructions" className="flex-1 min-h-0">
						<div className="flex-1 w-full overflow-y-auto p-5 rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card shadow-[0_1px_3px_rgba(33,36,31,0.04)] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
							{liveAgent.instructions ? (
								<MessageResponse className="text-[13px] text-[#1E2D28] dark:text-white leading-[1.65]">
									{liveAgent.instructions}
								</MessageResponse>
							) : (
								<p className="text-[13px] font-medium text-[#A3B5AD] dark:text-white/30 leading-[1.65]">
									No instructions
								</p>
							)}
						</div>
					</EditorSection>
				</div>

				{/* Right: Tools + Subagents (read-only) */}
				<div className="h-full w-full md:w-1/2 flex flex-col min-h-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<AgentToolList
						readOnly
						mcpServers={form.mcpServers}
						hasCodeInterpreter={form.hasCodeInterpreter}
					/>
					{isAdmin && (
						<AgentSubagentList
							readOnly
							agentId={agent.id}
							isSubagent={liveAgent.isSubagent}
							subagentIds={form.subagentIds}
							fallbackSubagents={liveAgent.subagents ?? []}
						/>
					)}
				</div>
			</div>

			<AgentPermissionsDialog
				open={permissionsOpen}
				onOpenChange={setPermissionsOpen}
				agentId={agent.id}
				ownerId={liveAgent.ownerId}
			/>

			<AgentTagsDialog
				open={tagsOpen}
				onOpenChange={setTagsOpen}
				agent={liveAgent}
			/>
		</div>
	);
}

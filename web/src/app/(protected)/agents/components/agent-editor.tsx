"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import EmojiPicker, { EmojiClickData, Theme } from "emoji-picker-react";
import { AGENT_COLORS, agentColorBackground } from "@/lib/colors";
import { useTheme } from "next-themes";
import {
	ShieldCheck,
	ArrowRight,
	ArchiveIcon,
	History,
	Pencil,
} from "lucide-react";
import {
	Agent,
	AgentDraft,
	AgentDraftUpdater,
	buildAgentDraft,
} from "@/types/agents";
import AgentToolList from "../[id]/components/agent-tool-list";
import AgentSubagentList from "../[id]/components/agent-subagent-list";
import { Streamdown } from "streamdown";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { SageDropdownMenu } from "@/components/ui/sage-dropdown-menu";
import AgentPermissionsDialog from "./agent-permissions-dialog";

interface AgentEditorProps {
	agent: Agent;
}

export default function AgentEditor({ agent }: AgentEditorProps) {
	const router = useRouter();
	const { resolvedTheme } = useTheme();
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const removeAgent = useAgentsStore((state) => state.removeAgent);
	const markAgentArchived = useThreadsStore((state) => state.markAgentArchived);
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";

	const liveAgent = useAgentsStore(
		(state) => state.agents.find((a) => a.id === agent.id) ?? agent,
	);

	const [draft, setDraft] = useState<AgentDraft | null>(null);
	const [isSaving, setIsSaving] = useState(false);
	const [saveError, setSaveError] = useState<string | null>(null);
	const [showEmojiPicker, setShowEmojiPicker] = useState(false);
	const [permissionsOpen, setPermissionsOpen] = useState(false);
	const emojiPickerRef = useRef<HTMLDivElement>(null);

	const isEditing = draft !== null;
	const baseline = useMemo(() => buildAgentDraft(liveAgent), [liveAgent]);
	const view = draft ?? baseline;
	const isDirty =
		draft !== null && JSON.stringify(draft) !== JSON.stringify(baseline);

	const emoji = view.emoji || "🤖";
	const color = view.color || AGENT_COLORS[0];

	const canManageAgent =
		liveAgent.currentUserPermission === "owner" ||
		liveAgent.currentUserPermission === "admin";
	const canEdit =
		canManageAgent || liveAgent.currentUserPermission === "editor";

	const handleDraftChange = useCallback((update: AgentDraftUpdater) => {
		setDraft((prev) => (prev ? update(prev) : prev));
	}, []);

	const startEditing = () => {
		setSaveError(null);
		setDraft(buildAgentDraft(liveAgent));
	};

	const cancelEditing = () => {
		setDraft(null);
		setSaveError(null);
		setShowEmojiPicker(false);
	};

	const handleSave = async () => {
		if (!draft) return;
		setIsSaving(true);
		setSaveError(null);
		try {
			const response = await api.put(`/agents/${agent.id}/config`, {
				name: draft.name.trim(),
				instructions: draft.instructions.trim(),
				description: draft.description.trim() || null,
				emoji: draft.emoji,
				color: draft.color,
				hasCodeInterpreter: draft.hasCodeInterpreter,
				mcpServers: draft.mcpServers,
				subagentIds: draft.subagents.map((s) => s.id),
			});
			updateAgent(agent.id, response.data);

			// Refresh agents whose subagent status changed so their
			// isSubagent flag stays accurate in the store.
			const before = new Set(
				(liveAgent.subagents || []).map((s) => s.id),
			);
			const after = new Set(draft.subagents.map((s) => s.id));
			const affected = [...new Set([...before, ...after])].filter(
				(id) => before.has(id) !== after.has(id),
			);
			await Promise.all(
				affected.map((id) =>
					api
						.get(`/agents/${id}`)
						.then((res) => updateAgent(id, res.data))
						.catch(() => {}),
				),
			);

			setDraft(null);
			setShowEmojiPicker(false);
		} catch (error) {
			console.error("Error saving agent:", error);
			setSaveError("Failed to save changes. Please try again.");
		} finally {
			setIsSaving(false);
		}
	};

	// Warn before leaving the page with unsaved changes
	useEffect(() => {
		if (!isDirty) return;
		const handleBeforeUnload = (event: BeforeUnloadEvent) => {
			event.preventDefault();
		};
		window.addEventListener("beforeunload", handleBeforeUnload);
		return () => {
			window.removeEventListener("beforeunload", handleBeforeUnload);
		};
	}, [isDirty]);

	useEffect(() => {
		const handleClickOutside = (event: MouseEvent) => {
			if (
				emojiPickerRef.current &&
				!emojiPickerRef.current.contains(event.target as Node)
			) {
				setShowEmojiPicker(false);
			}
		};

		if (showEmojiPicker) {
			document.addEventListener("mousedown", handleClickOutside);
		}

		return () => {
			document.removeEventListener("mousedown", handleClickOutside);
		};
	}, [showEmojiPicker]);

	const handleEmojiClick = (emojiData: EmojiClickData) => {
		handleDraftChange((prev) => ({ ...prev, emoji: emojiData.emoji }));
		setShowEmojiPicker(false);
	};

	const handleColorClick = (c: string) => {
		handleDraftChange((prev) => ({ ...prev, color: c }));
	};

	const handleManagePermissions = () => {
		setPermissionsOpen(true);
	};

	const handleViewThreads = () => {
		router.push(`/agents/${agent.id}/threads`);
	};

	const handleDeleteAgent = async () => {
		if (
			!confirm(
				"Are you sure you want to archive this agent?",
			)
		) {
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

	return (
		<div className="h-full flex flex-col font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
			{/* Top bar */}
			<div className="flex flex-col md:flex-row md:items-center gap-3 md:gap-4 px-8 py-6 shrink-0 z-10 animate-in fade-in slide-in-from-bottom-3 duration-400" style={{ animationDelay: "0ms", animationFillMode: "both" }}>
				<div className="flex items-center gap-4 flex-1 min-w-0">
					<div className="relative">
						<div
							onClick={() => isEditing && setShowEmojiPicker(!showEmojiPicker)}
							style={{
								background: agentColorBackground(color),
								border: `1.5px solid ${color}18`,
							}}
							className={`flex items-center justify-center shrink-0 w-14 h-14 rounded-full text-[28px] transition-colors ${
								isEditing ? "cursor-pointer hover:opacity-80" : "cursor-default"
							}`}
						>
							{emoji}
						</div>
						{showEmojiPicker && (
							<div ref={emojiPickerRef} className="absolute top-full mt-2 z-50">
								<EmojiPicker
									onEmojiClick={handleEmojiClick}
									theme={resolvedTheme === "dark" ? Theme.DARK : Theme.LIGHT}
									skinTonesDisabled
									previewConfig={{ showPreview: false }}
								/>
								<div className="flex items-center justify-center gap-2 px-3 py-2 bg-white dark:bg-[#222] rounded-b-lg border-t border-gray-100 dark:border-gray-700">
									{AGENT_COLORS.map((c) => (
										<button
											key={c}
											type="button"
											onClick={() => handleColorClick(c)}
											style={{ backgroundColor: c }}
											className={`w-7 h-7 rounded-full cursor-pointer transition-transform hover:scale-110 ${
												color === c
													? "ring-2 ring-offset-2 ring-gray-400 dark:ring-offset-[#222]"
													: ""
											}`}
										/>
									))}
								</div>
							</div>
						)}
					</div>

					<div className="flex flex-col overflow-hidden flex-1">
						<input
							type="text"
							value={view.name}
							readOnly={!isEditing}
							onChange={(e) =>
								handleDraftChange((prev) => ({ ...prev, name: e.target.value }))
							}
							placeholder="Agent name"
							className="font-[family-name:var(--font-jakarta-sans)] text-[24px] font-extrabold text-[#1E2D28] dark:text-foreground leading-tight tracking-[-0.03em] truncate w-full bg-transparent border-none focus:outline-none focus:ring-0 p-0"
						/>
						<p className="text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium mt-0.5 truncate w-full">
							@{view.name.toLowerCase().replace(/\s+/g, "_") || "agent_name"}
						</p>
					</div>
				</div>

				<div className="flex items-center gap-2.5">
					{saveError && (
						<span className="text-[13px] font-semibold text-red-500">
							{saveError}
						</span>
					)}

					{isEditing ? (
						<>
							{/* Cancel button */}
							<button
								className="flex items-center gap-2 px-5.5 py-2.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent text-[14px] font-semibold text-[#6B7F76] dark:text-muted-foreground cursor-pointer transition-all hover:border-[#A3B5AD] disabled:opacity-50"
								onClick={cancelEditing}
								disabled={isSaving}
							>
								Cancel
							</button>

							{/* Save button */}
							<button
								className="flex items-center gap-2 px-5.5 py-2.5 rounded-full bg-[#111111] dark:bg-white text-white dark:text-[#111111] text-[14px] font-semibold cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] transition-all hover:opacity-90 disabled:opacity-50 disabled:cursor-default"
								onClick={handleSave}
								disabled={isSaving || !isDirty || !view.name.trim()}
							>
								{isSaving ? "Saving..." : "Save"}
							</button>
						</>
					) : (
						<>
							{/* Edit button */}
							{canEdit && (
								<button
									className="flex items-center gap-2 px-5.5 py-2.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent text-[14px] font-semibold text-[#6B7F76] dark:text-muted-foreground cursor-pointer transition-all hover:border-[#A3B5AD]"
									onClick={startEditing}
								>
									<Pencil className="size-[14px]" />
									Edit
								</button>
							)}

							{/* Chat button */}
							<button
								className="flex items-center gap-2 px-5.5 py-2.5 rounded-full bg-[#111111] dark:bg-white text-white dark:text-[#111111] text-[14px] font-semibold cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] transition-all hover:opacity-90"
								onClick={() => router.push(`/agents/${agent.id}/chat`)}
							>
								Chat
								<ArrowRight className="size-[15px]" />
							</button>

							{/* More menu */}
							<SageDropdownMenu
								items={[
									...(canManageAgent
										? [
											{ label: "View thread history", icon: <History />, onClick: handleViewThreads },
											{ label: "Manage permissions", icon: <ShieldCheck />, onClick: handleManagePermissions },
											{ separator: true as const },
										]
										: []),
									{ label: "Archive agent", icon: <ArchiveIcon />, destructive: true, onClick: handleDeleteAgent },
								]}
							/>
						</>
					)}
				</div>
			</div>

			{/* Two column layout */}
			<div className="relative flex flex-col md:flex-row flex-1 min-h-0 px-8 gap-8">
				{/* Left: Description + Instructions */}
				<div className="h-full w-full md:flex-1 flex flex-col min-w-0 animate-in fade-in slide-in-from-bottom-3 duration-400" style={{ animationDelay: "50ms", animationFillMode: "both" }}>
					<div className="shrink-0 mb-7">
						<div className="flex items-center min-h-[34px] mb-2.5">
							<label className="text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em]">
								Description
							</label>
						</div>
						<input
							type="text"
							maxLength={255}
							className="w-full px-5 py-3.5 rounded-[18px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium text-[#1E2D28] dark:text-white placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 focus:outline-none focus:border-[#4CA882] transition-colors read-only:focus:border-[#E0E8E4] dark:read-only:focus:border-white/10"
							value={view.description}
							readOnly={!isEditing}
							onChange={(e) =>
								handleDraftChange((prev) => ({
									...prev,
									description: e.target.value,
								}))
							}
							placeholder="A short description of your agent..."
						/>
						{view.description.length > 240 && (
							<p className="text-xs text-[#B8C8C0] mt-1 text-right">
								{view.description.length}/255
							</p>
						)}
					</div>

					<div className="flex-1 flex flex-col min-h-0">
						<label className="block text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em] mb-2.5">
							Instructions
						</label>
						{isEditing ? (
							<textarea
								className="flex-1 w-full h-full px-5 py-4.5 rounded-[22px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium text-[#1E2D28] dark:text-white leading-relaxed placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 resize-vertical focus:outline-none focus:border-[#4CA882] transition-colors [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
								value={view.instructions}
								onChange={(e) =>
									handleDraftChange((prev) => ({
										...prev,
										instructions: e.target.value,
									}))
								}
								placeholder="Enter instructions for your agent..."
							/>
						) : (
							<div className="flex-1 w-full min-h-0 overflow-y-auto px-5 py-4.5 rounded-[22px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium text-[#1E2D28] dark:text-white leading-relaxed [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
								{view.instructions.trim() ? (
									<Streamdown className="size-full [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
										{view.instructions}
									</Streamdown>
								) : (
									<span className="text-[#A3B5AD] dark:text-white/30">
										No instructions yet.
									</span>
								)}
							</div>
						)}
					</div>
				</div>

				{/* Right: Tools + Subagents */}
				<div className="h-full w-full md:w-1/2 flex flex-col min-h-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden animate-in fade-in slide-in-from-bottom-3 duration-400" style={{ animationDelay: "100ms", animationFillMode: "both" }}>
						<AgentToolList
						agent={liveAgent}
						draft={draft}
						onDraftChange={handleDraftChange}
					/>
					{isAdmin && (
						<AgentSubagentList
							agent={liveAgent}
							draft={draft}
							onDraftChange={handleDraftChange}
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
		</div>
	);
}

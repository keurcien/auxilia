"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import EmojiPicker, { EmojiClickData, Theme } from "emoji-picker-react";
import { AGENT_COLORS, agentColorBackground } from "@/lib/colors";
import { useTheme } from "next-themes";
import { MoreVertical, ShieldCheck, ArrowRight, ArchiveIcon } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentToolList from "../[id]/components/agent-tool-list";
import AgentSubagentList from "../[id]/components/agent-subagent-list";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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

	const [name, setName] = useState(agent.name || "");
	const [instructions, setInstructions] = useState(agent.instructions || "");
	const [description, setDescription] = useState(agent.description || "");
	const [emoji, setEmoji] = useState(agent.emoji || "🤖");
	const [color, setColor] = useState(agent.color || AGENT_COLORS[0]);
	const [showEmojiPicker, setShowEmojiPicker] = useState(false);
	const [saveStatus, setSaveStatus] = useState<"saved" | "saving">("saved");
	const [permissionsOpen, setPermissionsOpen] = useState(false);
	const savingTimerRef = useRef<NodeJS.Timeout | undefined>(undefined);
	const emojiPickerRef = useRef<HTMLDivElement>(null);
	const nameTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
	const instructionsTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
	const descriptionTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);

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
		setEmoji(emojiData.emoji);
		setShowEmojiPicker(false);
		saveAgent({ emoji: emojiData.emoji });
	};

	const handleColorClick = (c: string) => {
		setColor(c);
		saveAgent({ color: c });
	};

	const saveAgent = useCallback(
		async (
			updates: Partial<
				Pick<Agent, "name" | "instructions" | "emoji" | "color" | "description">
			>,
		) => {
			setSaveStatus("saving");
			try {
				const response = await api.patch(`/agents/${agent.id}`, updates);
				const updatedAgent: Agent = response.data;
				updateAgent(agent.id, updatedAgent);
				if (savingTimerRef.current) clearTimeout(savingTimerRef.current);
				savingTimerRef.current = setTimeout(() => setSaveStatus("saved"), 500);
			} catch (error) {
				console.error("Error saving agent:", error);
			}
		},
		[agent.id, updateAgent],
	);

	const handleManagePermissions = () => {
		setPermissionsOpen(true);
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

	// Auto-save name changes with 300ms debounce
	useEffect(() => {
		if (!name.trim() || name === liveAgent.name) return;

		if (nameTimeoutRef.current) clearTimeout(nameTimeoutRef.current);
		nameTimeoutRef.current = setTimeout(() => {
			saveAgent({ name: name.trim() });
		}, 300);

		return () => {
			if (nameTimeoutRef.current) clearTimeout(nameTimeoutRef.current);
		};
	}, [name, liveAgent.name, saveAgent]);

	// Auto-save instructions with debounce
	useEffect(() => {
		if (instructionsTimeoutRef.current) {
			clearTimeout(instructionsTimeoutRef.current);
		}

		instructionsTimeoutRef.current = setTimeout(() => {
			if (instructions !== liveAgent.instructions) {
				saveAgent({ instructions: instructions.trim() });
			}
		}, 600);

		return () => {
			if (instructionsTimeoutRef.current) {
				clearTimeout(instructionsTimeoutRef.current);
			}
		};
	}, [instructions, liveAgent.instructions, saveAgent]);

	// Auto-save description with debounce
	useEffect(() => {
		if (descriptionTimeoutRef.current) {
			clearTimeout(descriptionTimeoutRef.current);
		}

		descriptionTimeoutRef.current = setTimeout(() => {
			if (description !== (liveAgent.description || "")) {
				saveAgent({ description: description.trim() });
			}
		}, 600);

		return () => {
			if (descriptionTimeoutRef.current) {
				clearTimeout(descriptionTimeoutRef.current);
			}
		};
	}, [description, liveAgent.description, saveAgent]);

	return (
		<div className="h-full flex flex-col font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
			{/* Top bar */}
			<div className="flex flex-col md:flex-row md:items-center gap-3 md:gap-4 px-8 py-6 shrink-0 z-10 animate-in fade-in slide-in-from-bottom-3 duration-400" style={{ animationDelay: "0ms", animationFillMode: "both" }}>
				<div className="flex items-center gap-4 flex-1 min-w-0">
					<div className="relative">
						<div
							onClick={() => setShowEmojiPicker(!showEmojiPicker)}
							style={{
								background: agentColorBackground(color),
								border: `1.5px solid ${color}18`,
							}}
							className="flex items-center justify-center shrink-0 w-14 h-14 rounded-full text-[28px] cursor-pointer transition-colors hover:opacity-80"
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
							value={name}
							onChange={(e) => setName(e.target.value)}
							placeholder="Agent name"
							className="font-[family-name:var(--font-jakarta-sans)] text-[24px] font-extrabold text-[#1E2D28] dark:text-foreground leading-tight tracking-[-0.03em] truncate w-full bg-transparent border-none focus:outline-none focus:ring-0 p-0"
						/>
						<p className="text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium mt-0.5 truncate w-full">
							@{name.toLowerCase().replace(/\s+/g, "_") || "agent_name"}
						</p>
					</div>
				</div>

				<div className="flex items-center gap-2.5">
					{/* Save status pill */}
					<div
						className={`inline-flex items-center gap-1.5 rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-all duration-300 ${
							saveStatus === "saving"
								? "bg-[#FFF5CC] dark:bg-amber-950/40 text-[#D4A832] dark:text-amber-400"
								: "bg-[#EDF4F0] dark:bg-emerald-950/40 text-[#3D8B63] dark:text-emerald-400"
						}`}
					>
						<span
							className={`block w-[7px] h-[7px] rounded-full transition-all duration-300 ${
								saveStatus === "saving"
									? "bg-[#FDCB6E] animate-pulse-dot"
									: "bg-[#4CA882]"
							}`}
						/>
						{saveStatus === "saving" ? "Saving..." : "Saved"}
					</div>

					{/* Chat button */}
					<button
						className="flex items-center gap-2 px-5.5 py-2.5 rounded-full bg-[#111111] dark:bg-white text-white dark:text-[#111111] text-[14px] font-semibold cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] transition-all hover:opacity-90"
						onClick={() => router.push(`/agents/${agent.id}/chat`)}
					>
						Chat
						<ArrowRight className="size-[15px]" />
					</button>

					{/* More menu */}
					<DropdownMenu>
						<DropdownMenuTrigger asChild>
							<button className="w-10 h-10 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15">
								<MoreVertical className="w-[18px] h-[18px] text-[#6B7F76]" />
								<span className="sr-only">Agent settings</span>
							</button>
						</DropdownMenuTrigger>
						<DropdownMenuContent side="bottom" align="end">
							<DropdownMenuItem
								className="text-primary focus:text-primary cursor-pointer"
								onClick={handleManagePermissions}
							>
								<ShieldCheck className="size-4" />
								<span>Manage permissions</span>
							</DropdownMenuItem>
							<DropdownMenuItem
								className="text-destructive focus:text-destructive cursor-pointer"
								onClick={handleDeleteAgent}
							>
								<ArchiveIcon className="size-4 text-destructive" />
								<span>Archive agent</span>
							</DropdownMenuItem>
						</DropdownMenuContent>
					</DropdownMenu>
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
							className="w-full px-5 py-3.5 rounded-[18px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium text-[#1E2D28] dark:text-white placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 focus:outline-none focus:border-[#4CA882] transition-colors"
							value={description}
							onChange={(e) => setDescription(e.target.value)}
							placeholder="A short description of your agent..."
						/>
						{description.length > 240 && (
							<p className="text-xs text-[#B8C8C0] mt-1 text-right">
								{description.length}/255
							</p>
						)}
					</div>

					<div className="flex-1 flex flex-col min-h-0">
						<label className="block text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em] mb-2.5">
							Instructions
						</label>
						<textarea
							className="flex-1 w-full h-full px-5 py-4.5 rounded-[22px] border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 text-[14px] font-medium text-[#1E2D28] dark:text-white leading-relaxed placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 resize-vertical focus:outline-none focus:border-[#4CA882] transition-colors [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
							value={instructions}
							onChange={(e) => setInstructions(e.target.value)}
							placeholder="Enter instructions for your agent..."
						/>
					</div>
				</div>

				{/* Right: Tools + Subagents */}
				<div className="h-full w-full md:w-1/2 flex flex-col min-h-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden animate-in fade-in slide-in-from-bottom-3 duration-400" style={{ animationDelay: "100ms", animationFillMode: "both" }}>
					<AgentToolList
						agent={liveAgent}
						onSaving={() => setSaveStatus("saving")}
						onSaved={() => {
							if (savingTimerRef.current) clearTimeout(savingTimerRef.current);
							savingTimerRef.current = setTimeout(
								() => setSaveStatus("saved"),
								400,
							);
						}}
					/>
					{isAdmin && (
						<AgentSubagentList
							agent={liveAgent}
							onSaving={() => setSaveStatus("saving")}
							onSaved={() => {
								if (savingTimerRef.current) clearTimeout(savingTimerRef.current);
								savingTimerRef.current = setTimeout(
									() => setSaveStatus("saved"),
									400,
								);
							}}
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

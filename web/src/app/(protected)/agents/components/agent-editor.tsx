"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import EmojiPicker, { EmojiClickData, Theme } from "emoji-picker-react";
import { useTheme } from "next-themes";
import { MoreVertical, Trash2, ShieldCheck } from "lucide-react";
import { Agent } from "@/types/agents";
import AgentMCPServerList from "../[id]/components/agent-mcp-server-list";
import { api } from "@/lib/api/client";
import { useAgentsStore } from "@/stores/agents-store";
import { Button } from "@/components/ui/button";
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

	const liveAgent = useAgentsStore(
		(state) => state.agents.find((a) => a.id === agent.id) ?? agent,
	);

	const [name, setName] = useState(agent.name || "");
	const [instructions, setInstructions] = useState(agent.instructions || "");
	const [description, setDescription] = useState(agent.description || "");
	const [emoji, setEmoji] = useState(agent.emoji || "🤖");
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

	const saveAgent = useCallback(
		async (
			updates: Partial<
				Pick<Agent, "name" | "instructions" | "emoji" | "description">
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
				"Are you sure you want to delete this agent?",
			)
		) {
			return;
		}

		try {
			await api.delete(`/agents/${agent.id}`);
			removeAgent(agent.id);
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
		<div className="h-full flex flex-col">
			<div className="flex items-center gap-4 p-6 py-4 shrink-0">
				<div className="relative">
					<div
						onClick={() => setShowEmojiPicker(!showEmojiPicker)}
						className="flex items-center justify-center shrink-0 w-16 h-16 rounded-2xl bg-muted text-3xl cursor-pointer hover:bg-muted/80 transition-colors"
					>
						{emoji}
					</div>
					{showEmojiPicker && (
						<div ref={emojiPickerRef} className="absolute top-full mt-2 z-50">
							<EmojiPicker
								onEmojiClick={handleEmojiClick}
								theme={resolvedTheme === "dark" ? Theme.DARK : Theme.LIGHT}
							/>
						</div>
					)}
				</div>

				<div className="flex flex-col overflow-hidden flex-1">
					<input
						type="text"
						value={name}
						onChange={(e) => setName(e.target.value)}
						placeholder="Agent name"
						className="text-2xl font-bold text-foreground leading-tight truncate w-full bg-transparent border-none focus:outline-none focus:ring-0 p-0"
					/>
					<p className="text-lg text-muted-foreground truncate w-full">
						@{name.toLowerCase().replace(/\s+/g, "_") || "agent_name"}
					</p>
				</div>

				<div
					className={`inline-flex items-center gap-2 rounded-2xl px-3.5 py-2 text-base ${
						saveStatus === "saving"
							? "bg-amber-50 dark:bg-amber-950/40"
							: "bg-emerald-50 dark:bg-emerald-950/40"
					}`}
				>
					<span
						className={`block size-2 rounded-full ${
							saveStatus === "saving"
								? "bg-amber-500 animate-pulse-dot"
								: "bg-emerald-500"
						}`}
					/>
					<span
						className={`text-sm font-medium leading-none ${
							saveStatus === "saving"
								? "text-amber-700 dark:text-amber-400"
								: "text-emerald-700 dark:text-emerald-400"
						}`}
					>
						{saveStatus === "saving" ? "Saving" : "Saved"}
					</span>
				</div>

				<DropdownMenu>
					<DropdownMenuTrigger asChild>
						<Button variant="ghost" size="icon" className="cursor-pointer">
							<MoreVertical className="w-5 h-5" />
							<span className="sr-only">Agent settings</span>
						</Button>
					</DropdownMenuTrigger>
					<DropdownMenuContent side="bottom" align="end">
						<DropdownMenuItem
							className="text-primary focus:text-primary cursor-pointer"
							onClick={handleManagePermissions}
						>
							<ShieldCheck className="size-4 mr-2" />
							<span>Manage permissions</span>
						</DropdownMenuItem>
						<DropdownMenuItem
							className="text-destructive focus:text-destructive cursor-pointer"
							onClick={handleDeleteAgent}
						>
							<Trash2 className="size-4 mr-2 text-destructive" />
							<span>Delete agent</span>
						</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
			</div>

			<div className="relative flex flex-col md:flex-row flex-1 min-h-0">
				<div className="h-full w-full md:w-1/2 flex flex-col p-6">
					<div className="shrink-0 mb-4">
						<h2 className="h-[32px] text-muted-foreground text-sm leading-5 font-medium block mb-2">
							Description
						</h2>
						<input
							type="text"
							maxLength={255}
							className="h-[52px] w-full text-foreground bg-muted border border-muted rounded-lg px-4 py-3 font-noto text-sm focus:outline-none focus:ring-0 font-medium"
							value={description}
							onChange={(e) => setDescription(e.target.value)}
							placeholder="A short description of your agent..."
						/>
						{description.length > 240 && (
							<p className="text-xs text-muted-foreground mt-1 text-right">
								{description.length}/255
							</p>
						)}
					</div>

					<div className="flex-1 flex flex-col min-h-0">
						<h2 className="text-muted-foreground text-sm leading-5 font-medium block mb-4">
							Instructions
						</h2>

						<div className="prose prose-gray max-w-none flex-1 flex flex-col min-h-0">
							<textarea
								className="flex-1 w-full h-full text-foreground bg-muted rounded-lg px-4 py-3 resize-none font-noto text-sm focus:outline-none focus:ring-0 font-medium [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
								value={instructions}
								onChange={(e) => setInstructions(e.target.value)}
								placeholder="Enter instructions for your agent..."
							/>
						</div>
					</div>
				</div>

				<div className="h-full w-full md:w-1/2 p-6 flex flex-col min-h-0">
					<AgentMCPServerList
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

"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import EmojiPicker, { EmojiClickData } from "emoji-picker-react";
import { Check, Loader2, MoreVertical, Trash2 } from "lucide-react";
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

interface AgentEditorProps {
	agent: Agent;
}

export default function AgentEditor({ agent }: AgentEditorProps) {
	const router = useRouter();
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const removeAgent = useAgentsStore((state) => state.removeAgent);

	const liveAgent = useAgentsStore(
		(state) => state.agents.find((a) => a.id === agent.id) ?? agent,
	);

	const [name, setName] = useState(agent.name || "");
	const [instructions, setInstructions] = useState(agent.instructions || "");
	const [emoji, setEmoji] = useState(agent.emoji || "🤖");
	const [showEmojiPicker, setShowEmojiPicker] = useState(false);
	const [saveStatus, setSaveStatus] = useState<"saved" | "saving">("saved");
	const emojiPickerRef = useRef<HTMLDivElement>(null);
	const nameTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
	const instructionsTimeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);

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
	};

	const saveAgent = useCallback(
		async (
			updates: Partial<Pick<Agent, "name" | "instructions" | "emoji">>,
		) => {
			try {
				const response = await api.patch(`/agents/${agent.id}`, updates);
				const updatedAgent: Agent = response.data;
				updateAgent(agent.id, updatedAgent);
				setSaveStatus("saved");
			} catch (error) {
				console.error("Error saving agent:", error);
			}
		},
		[agent.id, updateAgent],
	);

	const handleDeleteAgent = async () => {
		if (
			!confirm(
				"Are you sure you want to delete this agent? This action cannot be undone.",
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

		setSaveStatus("saving");

		if (nameTimeoutRef.current) clearTimeout(nameTimeoutRef.current);
		nameTimeoutRef.current = setTimeout(() => {
			saveAgent({ name: name.trim() });
		}, 300);

		return () => {
			if (nameTimeoutRef.current) clearTimeout(nameTimeoutRef.current);
		};
	}, [name, liveAgent.name, saveAgent]);

	// Auto-save emoji changes
	useEffect(() => {
		if (emoji !== liveAgent.emoji) {
			setSaveStatus("saving");
			saveAgent({ emoji });
		}
	}, [emoji, liveAgent.emoji, saveAgent]);

	// Auto-save instructions with debounce
	useEffect(() => {
		if (instructions !== liveAgent.instructions) {
			setSaveStatus("saving");
		}

		if (instructionsTimeoutRef.current) {
			clearTimeout(instructionsTimeoutRef.current);
		}

		instructionsTimeoutRef.current = setTimeout(() => {
			if (instructions !== liveAgent.instructions) {
				saveAgent({ instructions: instructions.trim() });
			}
		}, 1000);

		return () => {
			if (instructionsTimeoutRef.current) {
				clearTimeout(instructionsTimeoutRef.current);
			}
		};
	}, [instructions, liveAgent.instructions, saveAgent]);

	return (
		<div className="h-full flex flex-col">
			<div className="flex items-center gap-4 p-6 py-4 shrink-0">
				<div className="relative">
					<div
						onClick={() => setShowEmojiPicker(!showEmojiPicker)}
						className="flex items-center justify-center shrink-0 w-16 h-16 rounded-2xl bg-gray-100 text-3xl cursor-pointer hover:bg-gray-200 transition-colors"
					>
						{emoji}
					</div>
					{showEmojiPicker && (
						<div ref={emojiPickerRef} className="absolute top-full mt-2 z-50">
							<EmojiPicker onEmojiClick={handleEmojiClick} />
						</div>
					)}
				</div>

				<div className="flex flex-col overflow-hidden flex-1">
					<input
						type="text"
						value={name}
						onChange={(e) => setName(e.target.value)}
						placeholder="Agent name"
						className="text-2xl font-bold text-gray-900 leading-tight truncate w-full bg-transparent border-none focus:outline-none focus:ring-0 p-0"
					/>
					<p className="text-lg text-gray-500 truncate w-full">
						@{name.toLowerCase().replace(/\s+/g, "_") || "agent_name"}
					</p>
				</div>

				<div className="flex items-center gap-1.5 shrink-0">
					{saveStatus === "saved" ? (
						<>
							<Check className="w-5 h-5 text-green-500" />
							<span className="text-base text-green-500 font-medium">Saved</span>
						</>
					) : (
						<>
							<Loader2 className="w-5 h-5 text-yellow-500 animate-spin" />
							<span className="text-base text-yellow-500 font-medium">Saving</span>
						</>
					)}
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
							className="text-destructive focus:text-destructive cursor-pointer"
							onClick={handleDeleteAgent}
						>
							<Trash2 className="size-4 mr-2" />
							<span>Delete agent</span>
						</DropdownMenuItem>
					</DropdownMenuContent>
				</DropdownMenu>
			</div>

			<div className="relative flex flex-col md:flex-row flex-1 min-h-0">
				<div className="h-full w-full md:w-1/2 flex flex-col">
					<div className="w-full p-6 flex flex-col flex-1">
						<h2 className="text-gray-500 text-sm leading-5 font-medium block mb-4">
							Instructions
						</h2>

						<div className="prose prose-gray max-w-none flex-1 flex flex-col">
							<textarea
								className="flex-1 w-full h-full text-gray-700 bg-gray-50 rounded-lg px-4 py-3 resize-none font-noto text-sm focus:outline-none focus:ring-0 font-medium [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
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
						onSaved={() => setSaveStatus("saved")}
					/>
				</div>
			</div>
		</div>
	);
}

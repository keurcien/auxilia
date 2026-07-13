"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import EmojiPicker, { EmojiClickData, Theme } from "emoji-picker-react";
import { AGENT_COLORS, agentPastel } from "@/lib/colors";
import { useTheme } from "next-themes";
import { Agent } from "@/types/agents";
import AgentToolList from "../[id]/components/agent-tool-list";
import AgentSubagentList from "../[id]/components/agent-subagent-list";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useAgentsStore } from "@/stores/agents-store";
import { useUserStore } from "@/stores/user-store";
import { EditorHeader } from "@/components/editor/editor-header";
import { EditorSection } from "@/components/editor/editor-section";
import { SaveActions } from "@/components/editor/save-actions";
import {
	AgentFormState,
	defaultAgentForm,
	fromAgent,
	isFormDirty,
	toPayload,
} from "../lib/agent-form";

interface AgentEditorProps {
	/** Undefined = create mode (`/agents/new` draft). */
	agent?: Agent;
	onSaved: (agent: Agent) => void;
	onCancel: () => void;
}

export default function AgentEditor({
	agent,
	onSaved,
	onCancel,
}: AgentEditorProps) {
	const { resolvedTheme } = useTheme();
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const addAgent = useAgentsStore((state) => state.addAgent);
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";

	// Snapshot taken on entering edit mode — the dirty baseline. Deliberately
	// NOT re-derived from the store mid-edit.
	const initialForm = useMemo(
		() => (agent ? fromAgent(agent) : defaultAgentForm()),
		[agent],
	);
	const [form, setForm] = useState<AgentFormState>(initialForm);
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [showEmojiPicker, setShowEmojiPicker] = useState(false);
	const emojiPickerRef = useRef<HTMLDivElement>(null);

	const setField = <K extends keyof AgentFormState>(
		key: K,
		value: AgentFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const isDirty = isFormDirty(form, initialForm);
	const canSave = Boolean(form.name.trim() && form.instructions.trim());

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

	// Warn before leaving the page with unsaved changes.
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

	const handleEmojiClick = (emojiData: EmojiClickData) => {
		setField("emoji", emojiData.emoji);
		setShowEmojiPicker(false);
	};

	const handleSave = async () => {
		if (!canSave) return;
		setIsSaving(true);
		setError(null);
		try {
			const response = agent
				? await api.put(`/agents/${agent.id}/config`, toPayload(form))
				: await api.post("/agents", toPayload(form));
			const saved: Agent = response.data;
			if (agent) {
				updateAgent(agent.id, saved);
			} else {
				addAgent(saved);
			}

			// Refresh agents whose isSubagent flag changed with this save.
			const before = new Set(initialForm.subagentIds);
			const after = new Set(form.subagentIds);
			const affected = [
				...form.subagentIds.filter((id) => !before.has(id)),
				...initialForm.subagentIds.filter((id) => !after.has(id)),
			];
			await Promise.all(
				affected.map((id) =>
					api
						.get(`/agents/${id}`)
						.then((res) => {
							updateAgent(id, res.data);
						})
						.catch(() => {}),
				),
			);

			onSaved(saved);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save the agent."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleCancel = () => {
		if (isDirty && !confirm("Discard unsaved changes?")) {
			return;
		}
		onCancel();
	};

	return (
		<div className="h-full flex flex-col font-[family-name:var(--font-dm-sans)] animate-in fade-in duration-300">
			<div className="px-8 py-6 shrink-0 z-10">
				<EditorHeader
					icon={
						<div className="relative size-full">
							<div
								onClick={() => { setShowEmojiPicker(!showEmojiPicker); }}
								style={{ background: agentPastel(form.color).pill }}
								className="flex items-center justify-center size-full rounded-[13px] text-[23px] cursor-pointer transition-opacity hover:opacity-80"
							>
								{form.emoji}
							</div>
							{showEmojiPicker && (
								<div ref={emojiPickerRef} className="absolute top-full left-0 mt-2 z-50">
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
												onClick={() => { setField("color", c); }}
												style={{ backgroundColor: c }}
												className={`w-7 h-7 rounded-full cursor-pointer transition-transform hover:scale-110 ${
													form.color === c
														? "ring-2 ring-offset-2 ring-gray-400 dark:ring-offset-[#222]"
														: ""
												}`}
											/>
										))}
									</div>
								</div>
							)}
						</div>
					}
					title={agent ? "Edit agent" : "New agent"}
					subtitle={
						agent?.name ? (
							<span className="font-[family-name:var(--font-dm-sans)] text-[12.5px] font-medium text-[#94A59D] dark:text-muted-foreground truncate">
								{agent.name}
							</span>
						) : undefined
					}
					actions={
						<SaveActions
							isDirty={isDirty}
							isSaving={isSaving}
							canSave={canSave}
							onSave={() => {
								void handleSave();
							}}
							onCancel={handleCancel}
							saveLabel={agent ? "Save changes" : "Create agent"}
						/>
					}
				/>

				{error && (
					<div className="mt-5 rounded-[14px] bg-[#FFF5F3] dark:bg-[#D45B45]/10 px-4 py-3 text-[13.5px] font-medium text-[#D45B45]">
						{error}
					</div>
				)}
			</div>

			{/* Two column layout */}
			<div className="relative flex flex-col md:flex-row flex-1 min-h-0 px-8 gap-8">
				{/* Left: Name + Description + Instructions */}
				<div className="h-full w-full md:flex-1 flex flex-col min-w-0">
					<EditorSection label="Agent name" className="shrink-0 mb-7">
						<input
							type="text"
							maxLength={255}
							value={form.name}
							onChange={(e) => { setField("name", e.target.value); }}
							placeholder="What is this agent called?"
							className="w-full px-[17px] py-[15px] rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card text-[15px] font-semibold text-[#1E2D28] dark:text-white leading-[1.5] placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 shadow-[0_1px_3px_rgba(33,36,31,0.04)] focus:outline-none focus:border-[#4CA882] transition-colors"
						/>
					</EditorSection>

					<EditorSection label="Description" className="shrink-0 mb-7">
						<input
							type="text"
							maxLength={255}
							className="w-full px-[17px] py-[15px] rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card text-[13.5px] font-medium text-[#1E2D28] dark:text-white leading-[1.5] placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 shadow-[0_1px_3px_rgba(33,36,31,0.04)] focus:outline-none focus:border-[#4CA882] transition-colors"
							value={form.description}
							onChange={(e) => { setField("description", e.target.value); }}
							placeholder="A short description of your agent..."
						/>
						{form.description.length > 240 && (
							<p className="text-xs text-[#B8C8C0] mt-1 text-right">
								{form.description.length}/255
							</p>
						)}
					</EditorSection>

					<EditorSection label="Instructions" className="flex-1 min-h-0">
						<textarea
							className="flex-1 w-full h-full p-5 rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card text-[13px] font-medium text-[#1E2D28] dark:text-white leading-[1.65] placeholder:text-[#A3B5AD] dark:placeholder:text-white/30 resize-none shadow-[0_1px_3px_rgba(33,36,31,0.04)] focus:outline-none focus:border-[#4CA882] transition-colors [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
							value={form.instructions}
							onChange={(e) => { setField("instructions", e.target.value); }}
							placeholder="Enter instructions for your agent..."
						/>
					</EditorSection>
				</div>

				{/* Right: Tools + Subagents */}
				<div className="h-full w-full md:w-1/2 flex flex-col min-h-0 overflow-y-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<AgentToolList
						mcpServers={form.mcpServers}
						hasCodeInterpreter={form.hasCodeInterpreter}
						onMcpServersChange={(mcpServers) => { setField("mcpServers", mcpServers); }}
						onHasCodeInterpreterChange={(enabled) => { setField("hasCodeInterpreter", enabled); }}
					/>
					{isAdmin && (
						<AgentSubagentList
							agentId={agent?.id ?? ""}
							isSubagent={agent?.isSubagent ?? false}
							subagentIds={form.subagentIds}
							fallbackSubagents={agent?.subagents ?? []}
							onChange={(subagentIds) => { setField("subagentIds", subagentIds); }}
						/>
					)}
				</div>
			</div>
		</div>
	);
}

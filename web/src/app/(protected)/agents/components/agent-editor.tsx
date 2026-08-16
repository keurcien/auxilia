"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import EmojiPicker, { EmojiClickData, Theme } from "emoji-picker-react";
import { ArchiveIcon, History, Pencil, Play } from "lucide-react";
import { AGENT_COLORS, agentPastel } from "@/lib/colors";
import { useTheme } from "next-themes";
import { Agent } from "@/types/agents";
import AgentToolList from "../[id]/components/agent-tool-list";
import AgentSubagentList from "../[id]/components/agent-subagent-list";
import AgentTagsPanel from "./agent-tags-panel";
import AgentPermissionsPanel from "./agent-permissions-panel";
import { MessageResponse } from "@/components/ai-elements/message";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useAgentsStore } from "@/stores/agents-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { cn } from "@/lib/utils";
import {
	AgentFormState,
	defaultAgentForm,
	fromAgent,
	isFormDirty,
	toPayload,
} from "../lib/agent-form";

type EditorTab = "instructions" | "tags" | "permissions";

const slugify = (name: string) =>
	name.trim().toLowerCase().replace(/\s+/g, "-") || "…";

interface AgentEditorProps {
	/** Undefined = create mode (`/agents/new` draft). */
	agent?: Agent;
	/** Read mode — inputs render disabled, instructions as markdown. */
	readOnly?: boolean;
	/** Provided in read mode when the viewer may edit — shows the Edit button. */
	onEdit?: () => void;
	onSaved: (agent: Agent) => void;
	/** Discard/Cancel: back to read mode (detail) or leave the page (create). */
	onCancel: () => void;
}

export default function AgentEditor({
	agent,
	readOnly = false,
	onEdit,
	onSaved,
	onCancel,
}: AgentEditorProps) {
	const router = useRouter();
	const { resolvedTheme } = useTheme();
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const addAgent = useAgentsStore((state) => state.addAgent);
	const removeAgent = useAgentsStore((state) => state.removeAgent);
	const markAgentArchived = useThreadsStore((state) => state.markAgentArchived);
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";

	const canManageAgent =
		agent?.currentUserPermission === "owner" ||
		agent?.currentUserPermission === "admin";

	// Tag assignment is an instant action (own PATCH, not part of the config
	// draft), so it stays available to editors even in read mode.
	const canEditAgent =
		!agent ||
		canManageAgent ||
		agent.currentUserPermission === "editor";

	// Snapshot taken on mount — the dirty baseline. Re-derives when the agent
	// is saved (the store hands back a fresh object), never from form edits.
	const initialForm = useMemo(
		() => (agent ? fromAgent(agent) : defaultAgentForm()),
		[agent],
	);
	const [form, setForm] = useState<AgentFormState>(initialForm);
	const [tab, setTab] = useState<EditorTab>("instructions");
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

	const isDirty = !readOnly && isFormDirty(form, initialForm);
	const canSave = Boolean(form.name.trim() && form.instructions.trim());

	const tabs: { key: EditorTab; label: string }[] = [
		{ key: "instructions", label: "Instructions" },
		// Tags/permissions act on the saved agent — they appear once it exists.
		...(agent ? [{ key: "tags" as const, label: "Tags" }] : []),
		...(agent && canManageAgent
			? [{ key: "permissions" as const, label: "Permissions" }]
			: []),
	];

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

	const handleDiscard = () => {
		if (isDirty && !confirm("Discard unsaved changes?")) {
			return;
		}
		onCancel();
	};

	const handleArchive = async () => {
		if (!agent) return;
		if (!confirm("Are you sure you want to archive this agent?")) {
			return;
		}
		try {
			await api.delete(`/agents/${agent.id}`);
			removeAgent(agent.id);
			markAgentArchived(agent.id);
			router.push("/agents");
		} catch (err) {
			console.error("Error archiving agent:", err);
			setError(getApiErrorMessage(err, "Failed to archive the agent."));
		}
	};

	const fieldInputClass =
		"w-full rounded-lg border border-input bg-card px-3 py-[7px] outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default";

	return (
		<div className="flex h-svh min-w-0 flex-1 flex-col bg-background animate-in fade-in duration-300">
			{/* Header bar */}
			<header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border pl-14 pr-4 md:px-7">
				<span className="min-w-0 truncate font-mono text-[11.5px] text-meta dark:text-panel-dim">
					<Link href="/agents" className="transition-colors hover:text-foreground">
						agents
					</Link>{" "}
					<span className="text-ghost dark:text-panel-dim">/</span>{" "}
					<span className="font-medium text-foreground">
						{slugify(form.name)}
					</span>
				</span>
				{isDirty && (
					<span className="rounded-[4px] bg-warning-bg px-2 py-0.5 font-mono text-[10px] font-semibold tracking-[0.05em] text-warning">
						UNSAVED
					</span>
				)}
				<div className="ml-auto flex shrink-0 items-center gap-2">
					{agent && (
						<button
							type="button"
							title="Opens the real chat with the last saved configuration"
							onClick={() => {
								router.push(`/agents/${agent.id}/chat`);
							}}
							className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-4 py-2 text-[13px] font-semibold text-petrol transition-colors hover:border-border-hover"
						>
							<Play className="size-3" fill="currentColor" />
							Test in chat
						</button>
					)}
					{readOnly && onEdit && (
						<button
							type="button"
							onClick={onEdit}
							className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90"
						>
							Edit
						</button>
					)}
					{!readOnly && (
						<>
							<button
								type="button"
								disabled={isSaving}
								onClick={handleDiscard}
								className="cursor-pointer rounded-[7px] border border-input bg-card px-4 py-2 text-[13px] font-semibold text-foreground transition-colors hover:border-border-hover disabled:cursor-not-allowed disabled:opacity-50"
							>
								{agent ? "Discard" : "Cancel"}
							</button>
							<button
								type="button"
								disabled={isSaving || !canSave || Boolean(agent && !isDirty)}
								onClick={() => {
									void handleSave();
								}}
								className="cursor-pointer rounded-[7px] bg-petrol px-[18px] py-2 text-[13px] font-semibold text-white transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
							>
								{isSaving
									? "Saving…"
									: agent
										? "Save changes"
										: "Create agent"}
							</button>
						</>
					)}
					{agent && canManageAgent && (
						<DropdownMenu
							items={[
								{
									label: "View thread history",
									icon: <History />,
									onClick: () => {
										router.push(`/agents/${agent.id}/threads`);
									},
								},
								{ separator: true as const },
								{
									label: "Archive agent",
									icon: <ArchiveIcon />,
									destructive: true,
									onClick: () => {
										void handleArchive();
									},
								},
							]}
						/>
					)}
				</div>
			</header>

			{error && (
				<div className="mx-7 mt-4 shrink-0 rounded-md bg-destructive/10 px-4 py-2.5 text-[13px] text-destructive">
					{error}
				</div>
			)}

			{/* Two panels: definition left, capabilities right */}
			<div className="flex min-h-0 flex-1 flex-col md:flex-row">
				{/* Left: identity + tabs */}
				<div className="flex min-w-0 flex-col overflow-y-auto border-b border-border bg-background p-7 md:flex-[1.05] md:border-b-0 md:border-r [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<div
						className={cn(
							"flex gap-3.5",
							readOnly ? "items-center" : "items-start",
						)}
					>
						<div className="relative shrink-0">
							<button
								type="button"
								disabled={readOnly}
								title={readOnly ? undefined : "Change emoji"}
								onClick={() => {
									setShowEmojiPicker(!showEmojiPicker);
								}}
								style={{ background: agentPastel(form.color).pill }}
								className="flex size-12 cursor-pointer items-center justify-center rounded-[10px] text-2xl shadow-[inset_0_0_0_1px_rgba(16,24,32,0.06)] transition-opacity hover:opacity-90 disabled:cursor-default disabled:hover:opacity-100"
							>
								{form.emoji}
							</button>
							{!readOnly && (
								<span className="pointer-events-none absolute -bottom-[5px] -right-[5px] flex size-[18px] items-center justify-center rounded-full border border-input bg-card shadow-raised">
									<Pencil className="size-[9px] text-subtle dark:text-panel-body" />
								</span>
							)}
							{showEmojiPicker && (
								<div
									ref={emojiPickerRef}
									className="absolute left-0 top-full z-50 mt-2"
								>
									<EmojiPicker
										onEmojiClick={handleEmojiClick}
										theme={resolvedTheme === "dark" ? Theme.DARK : Theme.LIGHT}
										skinTonesDisabled
										previewConfig={{ showPreview: false }}
									/>
									<div className="flex items-center justify-center gap-2 rounded-b-lg border-t border-border bg-card px-3 py-2">
										{AGENT_COLORS.map((c) => (
											<button
												key={c}
												type="button"
												onClick={() => {
													setField("color", c);
												}}
												style={{ backgroundColor: c }}
												className={`size-7 cursor-pointer rounded-full transition-transform hover:scale-110 ${
													form.color === c
														? "ring-2 ring-meta ring-offset-2"
														: ""
												}`}
											/>
										))}
									</div>
								</div>
							)}
						</div>
						{readOnly ? (
							// Most viewers never edit — the identity reads as plain text,
							// no input chrome.
							<div className="min-w-0 flex-1">
								<h1 className="w-full truncate py-[2px] font-mono text-[19px] font-semibold tracking-[-0.01em] text-petrol">
									{form.name}
								</h1>
								{/* Always rendered so the name keeps the same vertical
								    position whether or not a description exists. */}
								<p className="w-full truncate py-[2px] text-[13.5px] font-medium text-label dark:text-muted-foreground">
									{form.description || "\u00A0"}
								</p>
							</div>
						) : (
							<div className="flex min-w-0 flex-1 flex-col gap-1.5">
								<input
									type="text"
									maxLength={255}
									value={form.name}
									onChange={(e) => {
										setField("name", e.target.value);
									}}
									placeholder="Agent name"
									className={cn(
										fieldInputClass,
										"font-mono text-[15px] font-semibold tracking-[-0.01em] text-petrol",
									)}
								/>
								<input
									type="text"
									maxLength={255}
									value={form.description}
									onChange={(e) => {
										setField("description", e.target.value);
									}}
									placeholder="Describe what this agent does"
									className={cn(
										fieldInputClass,
										"text-[13px] font-medium text-body dark:text-panel-body",
									)}
								/>
							</div>
						)}
					</div>

					<UnderlineTabs
						tabs={tabs}
						value={tab}
						onChange={setTab}
						className="mt-6 border-b border-border"
					/>

					{/* Instructions fill the remaining panel height and scroll
					    internally when the text exceeds it. */}
					<div className="flex min-h-0 flex-1 flex-col pt-5">
						{tab === "instructions" &&
							(readOnly ? (
								<div className="min-h-[200px] w-full flex-1 overflow-y-auto rounded-lg border border-border bg-sidebar p-4 [scrollbar-width:thin]">
									{form.instructions ? (
										<MessageResponse className="text-[13px] leading-[1.65] text-foreground">
											{form.instructions}
										</MessageResponse>
									) : (
										<p className="text-[13px] text-meta dark:text-panel-dim">
											No instructions
										</p>
									)}
								</div>
							) : (
								<textarea
									value={form.instructions}
									onChange={(e) => {
										setField("instructions", e.target.value);
									}}
									placeholder="Enter instructions for your agent…"
									className="min-h-[300px] w-full flex-1 resize-none rounded-lg border border-input bg-sidebar p-4 font-mono text-[12.5px] leading-[1.7] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] [scrollbar-width:thin]"
								/>
							))}
						{tab === "tags" && agent && (
							<AgentTagsPanel agent={agent} canAssign={canEditAgent} />
						)}
						{tab === "permissions" && agent && canManageAgent && (
							<AgentPermissionsPanel
								agentId={agent.id}
								ownerId={agent.ownerId}
							/>
						)}
					</div>
				</div>

				{/* Right: capabilities */}
				<div className="min-w-0 overflow-y-auto bg-sidebar p-7 md:flex-1 dark:bg-white/[0.02] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
					<AgentToolList
						readOnly={readOnly}
						mcpServers={form.mcpServers}
						hasCodeInterpreter={form.hasCodeInterpreter}
						onMcpServersChange={(update) => {
							setForm((prev) => ({
								...prev,
								mcpServers: update(prev.mcpServers),
							}));
						}}
						onHasCodeInterpreterChange={(enabled) => {
							setField("hasCodeInterpreter", enabled);
						}}
					/>
					{isAdmin && (
						<AgentSubagentList
							readOnly={readOnly}
							agentId={agent?.id ?? ""}
							isSubagent={agent?.isSubagent ?? false}
							subagentIds={form.subagentIds}
							fallbackSubagents={agent?.subagents ?? []}
							onChange={(subagentIds) => {
								setField("subagentIds", subagentIds);
							}}
						/>
					)}
				</div>
			</div>
		</div>
	);
}

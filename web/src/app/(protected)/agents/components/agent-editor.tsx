"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import EmojiPicker, { EmojiClickData, Theme } from "emoji-picker-react";
import { ArchiveIcon, History, Pencil, Play } from "lucide-react";
import { toast } from "sonner";
import { AGENT_COLORS } from "@/lib/colors";
import { useTheme } from "next-themes";
import { Agent } from "@/types/agents";
import AgentToolList from "../[id]/components/agent-tool-list";
import AgentSubagentList from "../[id]/components/agent-subagent-list";
import AgentSkillList from "../[id]/components/agent-skill-list";
import { GroupPicker } from "@/components/ui/group-picker";
import AgentPermissionsPanel from "./agent-permissions-panel";
import { MessageResponse } from "@/components/ai-elements/message";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useAgentsStore } from "@/stores/agents-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useSkillsStore } from "@/stores/skills-store";
import { useUserStore } from "@/stores/user-store";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { cn } from "@/lib/utils";
import { groupOptions } from "@/lib/groups";
import * as agentsApi from "@/lib/api/resources/agents";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import {
	ImageFilePreview,
	ImageUpload,
} from "@/components/ui/image-upload";
import {
	AgentFormState,
	defaultAgentForm,
	fromAgent,
	isFormDirty,
	toPayload,
} from "../lib/agent-form";

type EditorTab = "instructions" | "permissions";

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
	const confirmDialog = useConfirmDialog();
	const { resolvedTheme } = useTheme();
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const createAgent = useAgentsStore((state) => state.createAgent);
	const saveAgentConfig = useAgentsStore((state) => state.saveAgentConfig);
	const refreshAgent = useAgentsStore((state) => state.refreshAgent);
	const archiveAgent = useAgentsStore((state) => state.archiveAgent);
	const workspaceAgents = useAgentsStore((state) => state.agents);
	const markAgentArchived = useThreadsStore((state) => state.markAgentArchived);
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";
	const librarySkills = useSkillsStore((state) => state.skills);

	const canManageAgent =
		agent?.currentUserPermission === "owner" ||
		agent?.currentUserPermission === "admin";

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
	const availableGroups = useMemo(
		() => groupOptions(workspaceAgents),
		[workspaceAgents],
	);
	// Enabled skills whose scripts need the sandbox — the tool list warns
	// before the sandbox is removed while any exist.
	const scriptSkillNames = useMemo(
		() =>
			form.skillIds
				.map(
					(id) =>
						librarySkills.find((s) => s.id === id) ??
						agent?.skills?.find((s) => s.id === id),
				)
				// A type predicate, so `map` sees a defined value: a plain boolean
				// filter does not narrow, which is what the `!` was standing in for.
				.filter((s): s is NonNullable<typeof s> => s !== undefined && s.scriptCount > 0)
				.map((s) => s.name),
		[form.skillIds, librarySkills, agent?.skills],
	);
	const [tab, setTab] = useState<EditorTab>("instructions");
	const [isSaving, setIsSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [showEmojiPicker, setShowEmojiPicker] = useState(false);
	const [imageFile, setImageFile] = useState<File | null>(null);
	const [removeImage, setRemoveImage] = useState(false);
	const currentImageUrl =
		agent?.id && agent.imageRevision
			? agentsApi.agentImageUrl(agent.id, agent.imageRevision)
			: null;
	// The "Add tool" dialog is controlled here so the Skills section can
	// open it ("Turn on code execution") on a skill whose scripts need one.
	const [addToolOpen, setAddToolOpen] = useState(false);
	const emojiPickerRef = useRef<HTMLDivElement>(null);

	const setField = <K extends keyof AgentFormState>(
		key: K,
		value: AgentFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const isDirty =
		!readOnly &&
		(isFormDirty(form, initialForm) || imageFile !== null || removeImage);
	// Read by callbacks that fire after an await (the subagent gate waits for
	// the agents store), so they see the draft as it is then, not at click.
	const isDirtyRef = useRef(isDirty);
	useEffect(() => {
		isDirtyRef.current = isDirty;
	}, [isDirty]);
	const canSave = Boolean(form.name.trim() && form.instructions.trim());

	const tabs: { key: EditorTab; label: string }[] = [
		{ key: "instructions", label: "Instructions" },
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
			let imageUploadFailed = false;
			let saved: Agent = agent
				? await saveAgentConfig(agent.id, toPayload(form))
				: await createAgent(toPayload(form));
			if (imageFile) {
				try {
					const revision = await agentsApi.uploadAgentImage(saved.id, imageFile);
					saved = { ...saved, imageRevision: revision };
					updateAgent(saved.id, saved);
				} catch (imageError) {
					if (agent) throw imageError;
					imageUploadFailed = true;
				}
			} else if (removeImage && saved.imageRevision) {
				await agentsApi.deleteAgentImage(saved.id);
				saved = { ...saved, imageRevision: null };
				updateAgent(saved.id, saved);
			}

			// Refresh agents whose isSubagent flag changed with this save.
			const before = new Set(initialForm.subagentIds);
			const after = new Set(form.subagentIds);
			const affected = [
				...form.subagentIds.filter((id) => !before.has(id)),
				...initialForm.subagentIds.filter((id) => !after.has(id)),
			];
			// Supervisor links changed: the linked agents' `isSubagent` flag did too.
			await Promise.all(affected.map((id) => refreshAgent(id).catch(() => {})));

			if (imageUploadFailed) {
				toast.warning("Agent created, but its image could not be uploaded.");
			}
			onSaved(saved);
		} catch (err) {
			setError(getApiErrorMessage(err, "Failed to save the agent."));
		} finally {
			setIsSaving(false);
		}
	};

	const handleDiscard = async () => {
		if (
			isDirty &&
			!(await confirmDialog({
				title: "Discard unsaved changes?",
				description: "Your edits will be lost and cannot be recovered.",
				confirmLabel: "Discard changes",
				destructive: true,
			}))
		) {
			return;
		}
		onCancel();
	};

	const handleArchive = async () => {
		if (!agent) return;
		if (
			!(await confirmDialog({
				title: "Archive this agent?",
				description:
					"The agent will no longer be available for new chats. You can restore it later from the archived agents view.",
				confirmLabel: "Archive agent",
				destructive: true,
			}))
		) {
			return;
		}
		try {
			await archiveAgent(agent.id);
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
				<span className="min-w-0 truncate text-[11.5px] text-meta dark:text-panel-dim">
					<Link href="/agents" className="transition-colors hover:text-foreground">
						agents
					</Link>{" "}
					<span className="text-ghost dark:text-panel-dim">/</span>{" "}
					<span className="font-medium text-foreground">
						{slugify(form.name)}
					</span>
				</span>
				{isDirty && (
					<span className="rounded-[4px] bg-warning-bg px-2 py-0.5 text-[10px] font-semibold text-warning">
						Unsaved
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
							className="flex cursor-pointer items-center gap-1.5 rounded-[7px] border border-input bg-card px-4 py-2 text-[13px] font-semibold text-petrol transition-colors hover:border-border-hover dark:border-white/10 dark:bg-white/[0.03] dark:text-panel-terminal dark:hover:border-white/20"
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
							onClick={() => {
								void handleDiscard();
							}}
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
						<div
							className={cn(
								"relative shrink-0",
								!readOnly && "mt-[22px]",
							)}
						>
							<button
								type="button"
								disabled={readOnly}
								aria-label={readOnly ? undefined : "Change agent identity"}
								title={readOnly ? undefined : "Change identity"}
								onClick={() => {
									setShowEmojiPicker(!showEmojiPicker);
								}}
								className="relative flex size-12 cursor-pointer items-center justify-center rounded-full text-2xl transition-opacity hover:opacity-90 disabled:cursor-default disabled:hover:opacity-100"
							>
								{imageFile ? (
									<ImageFilePreview file={imageFile} className="rounded-full" />
								) : (
									<AgentAvatar
										agentId={agent?.id}
										name={form.name}
										imageRevision={
											removeImage ? null : agent?.imageRevision
										}
										color={form.color}
										emoji={form.emoji}
										size="md"
										className="pointer-events-none size-full"
									/>
								)}
								{!readOnly && (
									<span className="absolute -bottom-[5px] -right-[5px] flex size-[18px] items-center justify-center rounded-full border border-input bg-card shadow-raised">
										<Pencil className="size-[9px] text-subtle dark:text-panel-body" />
									</span>
								)}
							</button>
							{showEmojiPicker && (
								<div
									ref={emojiPickerRef}
									className="absolute left-0 top-full z-50 mt-2"
								>
									<div className="rounded-t-lg border border-b-0 border-border bg-card p-3">
										<ImageUpload
											currentUrl={currentImageUrl}
											file={imageFile}
											removed={removeImage}
											onFileChange={(file) => {
												setImageFile(file);
												if (file) setRemoveImage(false);
											}}
											onRemove={() => {
												setImageFile(null);
												setRemoveImage(Boolean(agent?.imageRevision));
											}}
											label="Agent image"
											previewShape="circle"
										/>
									</div>
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
										<label
											title="Custom color"
											className={cn(
												"relative size-7 cursor-pointer overflow-hidden rounded-full bg-[conic-gradient(#e84393,#e17055,#fdcb6e,#00b894,#0984e3,#6c5ce7,#e84393)] transition-transform hover:scale-110",
												!AGENT_COLORS.includes(form.color) &&
													"ring-2 ring-meta ring-offset-2",
											)}
										>
											<span className="absolute inset-[5px] rounded-full border border-white/80 bg-card" />
											<input
												type="color"
												value={form.color}
												aria-label="Custom agent color"
												onChange={(event) => {
													setField("color", event.target.value.toUpperCase());
												}}
												className="absolute inset-0 size-full cursor-pointer opacity-0"
											/>
										</label>
									</div>
								</div>
							)}
						</div>
						{readOnly ? (
							// Most viewers never edit — the identity reads as plain text,
							// no input chrome.
							<div className="min-w-0 flex-1">
								<h1 className="w-full truncate py-[2px] text-[19px] font-semibold tracking-[-0.01em] text-petrol">
									{form.name}
								</h1>
								{/* Always rendered so the name keeps the same vertical
								    position whether or not a description exists. */}
								<p className="w-full truncate py-[2px] text-[13.5px] font-medium text-label dark:text-muted-foreground">
									{form.description || "\u00A0"}
								</p>
							</div>
						) : (
							<div className="flex min-w-0 flex-1 flex-col gap-4">
								<label>
									<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
										Name
									</span>
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
											"text-[15px] font-semibold tracking-[-0.01em] text-petrol dark:text-panel-terminal",
										)}
									/>
								</label>
								<label>
									<span className="mb-1.5 block text-[11px] font-semibold text-label dark:text-muted-foreground">
										Description{" "}
										<span className="font-normal text-meta">(Optional)</span>
									</span>
									<textarea
										maxLength={255}
										value={form.description}
										onChange={(e) => {
											setField("description", e.target.value);
										}}
										placeholder="Describe what this agent does"
										rows={3}
										className={cn(
											fieldInputClass,
											"resize-y py-2.5 text-[13px] font-medium leading-5 text-body dark:text-panel-body",
										)}
									/>
								</label>
								<GroupPicker
									value={form.group}
									groups={availableGroups}
									onChange={(group) => {
										setField("group", group);
									}}
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
									className="min-h-[300px] w-full flex-1 resize-none rounded-lg border border-input bg-sidebar p-4 text-[12.5px] leading-[1.7] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] [scrollbar-width:thin]"
								/>
							))}
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
						agentId={agent?.id}
						readOnly={readOnly}
						canEdit={canEditAgent}
						mcpServers={form.mcpServers}
						sandboxes={form.sandboxes}
						onMcpServersChange={(update) => {
							setForm((prev) => ({
								...prev,
								mcpServers: update(prev.mcpServers),
							}));
						}}
						onSandboxesChange={(sandboxes) => {
							setField("sandboxes", sandboxes);
						}}
						scriptSkillNames={scriptSkillNames}
						addDialogOpen={addToolOpen}
						onAddDialogOpenChange={setAddToolOpen}
						onBindingPersisted={(serverId, tools) => {
							// A read-mode sync wrote the binding server-side;
							// mirror it into the store so the next edit-mode
							// snapshot (and dirty baseline) starts from what is
							// actually saved. Read the store's latest copy, not
							// the `agent` prop: several bindings can self-heal
							// concurrently, and a render-closure snapshot would
							// let the later callback revert a sibling's map.
							if (!agent) return;
							const current =
								useAgentsStore
									.getState()
									.agents.find((a) => a.id === agent.id) ?? agent;
							updateAgent(agent.id, {
								mcpServers: (current.mcpServers ?? []).map((server) =>
									server.mcpServerId === serverId
										? { ...server, tools }
										: server,
								),
							});
						}}
					/>
					<AgentSkillList
						readOnly={readOnly}
						skillIds={form.skillIds}
						fallbackSkills={agent?.skills ?? []}
						runsCode={form.sandboxes.length > 0}
						onChange={(skillIds) => {
							setField("skillIds", skillIds);
						}}
						onEnableCodeExecution={() => {
							setAddToolOpen(true);
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
							confirmLeave={() =>
								!isDirtyRef.current
									? Promise.resolve(true)
									: confirmDialog({
											title: "Discard unsaved changes?",
											description:
												"Opening the subagent will leave this page and discard your edits.",
											confirmLabel: "Discard and leave",
											destructive: true,
										})
							}
						/>
					)}
				</div>
			</div>
		</div>
	);
}

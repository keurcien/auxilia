"use client";

import { useState, useMemo, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import EmojiPicker, { EmojiClickData, Theme } from "emoji-picker-react";
import {
	ArchiveIcon,
	Copy,
	History,
	Pencil,
	Play,
	Star,
} from "lucide-react";
import { toast } from "sonner";
import { AGENT_COLORS } from "@/lib/colors";
import { useTheme } from "next-themes";
import { Agent, ToolDiscoveryMode } from "@/types/agents";
import AgentToolList from "../[id]/components/agent-tool-list";
import AgentSubagentList from "../[id]/components/agent-subagent-list";
import AgentSkillList from "../[id]/components/agent-skill-list";
import AgentSideChannelCard from "../[id]/components/agent-side-channel-card";
import { GroupPicker } from "@/components/ui/group-picker";
import { VisibilityPicker } from "@/components/ui/visibility-picker";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import AgentLangfusePanel from "./agent-langfuse-panel";
import AgentPermissionsPanel from "./agent-permissions-panel";
import { MessageResponse } from "@/components/ai-elements/message";
import { getApiErrorMessage } from "@/lib/api/errors";
import { useAgentsStore } from "@/stores/agents-store";
import { useSkillsStore } from "@/stores/skills-store";
import { useModelsStore } from "@/stores/models-store";
import { useUserStore } from "@/stores/user-store";
import { useConfirmDialog } from "@/components/providers/dialog-provider";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { UnderlineTabs } from "@/components/ui/underline-tabs";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { groupOptions } from "@/lib/groups";
import { effortLabel } from "@/lib/reasoning-effort";
import { useIsMobile } from "@/hooks/use-mobile";
import { useUnsavedChangesWarning } from "@/hooks/use-unsaved-changes-warning";
import * as agentsApi from "@/lib/api/resources/agents";
import * as langfuseApi from "@/lib/api/resources/langfuse";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { UsageBadge } from "@/components/usage/usage-badge";
import { ModelPickerChip } from "@/components/editor/model-picker-chip";
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

export type EditorTab =
	| "instructions"
	| "versions"
	| "options"
	| "permissions"
	| "more";

export type CapabilityTab =
	| "mcp"
	| "skills"
	| "sandbox"
	| "slack"
	| "subagents";

const slugify = (name: string) =>
	name.trim().toLowerCase().replace(/\s+/g, "-") || "…";

const TOOL_DISCOVERY_LABELS: Record<ToolDiscoveryMode, string> = {
	disabled: "Eager",
	lazy: "Lazy",
	local: "Precision",
};

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
	initialTab?: EditorTab;
	onTabChange?: (tab: EditorTab) => void;
	initialCapabilityTab?: CapabilityTab;
	onCapabilityTabChange?: (tab: CapabilityTab) => void;
}

export default function AgentEditor({
	agent,
	readOnly = false,
	onEdit,
	onSaved,
	onCancel,
	initialTab = "instructions",
	onTabChange,
	initialCapabilityTab = "mcp",
	onCapabilityTabChange,
}: AgentEditorProps) {
	const router = useRouter();
	const confirmDialog = useConfirmDialog();
	const { resolvedTheme } = useTheme();
	const updateAgent = useAgentsStore((state) => state.updateAgent);
	const createAgent = useAgentsStore((state) => state.createAgent);
	const saveAgentConfig = useAgentsStore((state) => state.saveAgentConfig);
	const setDefaultAgent = useAgentsStore((state) => state.setDefaultAgent);
	const clearDefaultAgent = useAgentsStore((state) => state.clearDefaultAgent);
	const refreshAgent = useAgentsStore((state) => state.refreshAgent);
	const archiveAgent = useAgentsStore((state) => state.archiveAgent);
	const workspaceAgents = useAgentsStore((state) => state.agents);
	const models = useModelsStore((state) => state.models);
	const user = useUserStore((state) => state.user);
	const isAdmin = user?.role === "admin";
	const librarySkills = useSkillsStore((state) => state.skills);
	const isMobile = useIsMobile();

	const canManageAgent =
		agent?.currentUserPermission === "owner" ||
		agent?.currentUserPermission === "admin";

	const canEditAgent =
		!agent ||
		canManageAgent ||
		agent.currentUserPermission === "editor";
	const canSetDefaultAgent =
		Boolean(agent) && user?.role !== "member" && canEditAgent;
	const [isSettingDefault, setIsSettingDefault] = useState(false);

	// Snapshot taken on mount — the dirty baseline. Re-derives when the agent
	// is saved (the store hands back a fresh object), never from form edits.
	const initialForm = useMemo(
		() => (agent ? fromAgent(agent) : defaultAgentForm()),
		[agent],
	);
	const [form, setForm] = useState<AgentFormState>(initialForm);
	const selectedDefaultModel = models.find(
		(model) => model.id === form.defaultModelId,
	);
	const effortLevels = selectedDefaultModel?.reasoningEffortLevels ?? [];
	const validatedDefaultEffort =
		form.defaultReasoningEffort &&
		(selectedDefaultModel === undefined ||
			effortLevels.includes(form.defaultReasoningEffort))
			? form.defaultReasoningEffort
			: null;
	const defaultEffortLabel = validatedDefaultEffort
		? effortLabel(validatedDefaultEffort)
		: selectedDefaultModel?.reasoningEffortDefault
			? `Default (${effortLabel(selectedDefaultModel.reasoningEffortDefault)})`
			: "Auto";
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
	const [tab, setTab] = useState<EditorTab>(initialTab);
	const [capabilityTab, setCapabilityTab] =
		useState<CapabilityTab>(initialCapabilityTab);
	const [sideChannelCount, setSideChannelCount] = useState(0);
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
	const emojiTriggerRef = useRef<HTMLButtonElement>(null);
	const [langfuseEnabled, setLangfuseEnabled] = useState(false);
	const [langfuseVersion, setLangfuseVersion] =
		useState<langfuseApi.LangfusePromptVersion | null>(null);
	const [langfuseProduction, setLangfuseProduction] = useState<string | null>(
		null,
	);

	useEffect(() => {
		if (!agent) return;
		let active = true;
		void langfuseApi.isLangfuseEnabled().then((enabled) => {
			if (active) setLangfuseEnabled(enabled);
		});
		return () => {
			active = false;
		};
	}, [agent]);

	const agentId = agent?.id;
	useEffect(() => {
		if (!agentId) return;
		let active = true;
		void Promise.allSettled([
			agentsApi.listAgentSlackBots(agentId),
			agentsApi.listAgentTelegramBots(agentId),
			agentsApi.listAgentWhatsAppConnections(agentId),
		])
			.then(([slackResult, telegramResult, whatsAppResult]) => {
				if (active) {
					const slackCount =
						slackResult.status === "fulfilled"
							? slackResult.value.length
							: 0;
					const telegramCount =
						telegramResult.status === "fulfilled"
							? telegramResult.value.length
							: 0;
					const whatsAppCount =
						whatsAppResult.status === "fulfilled"
							? whatsAppResult.value.length
							: 0;
					setSideChannelCount(slackCount + telegramCount + whatsAppCount);
				}
			});
		return () => {
			active = false;
		};
	}, [agentId]);

	useEffect(() => {
		if (readOnly || !agentId || !canEditAgent || !langfuseEnabled) return;
		let active = true;
		void langfuseApi
			.getLangfusePrompt(agentId)
			.then((prompt) => {
				if (active) {
					setLangfuseProduction(prompt.production?.text ?? null);
				}
			})
			.catch(() => {
				// The Versions tab reports connectivity failures.
			});
		return () => {
			active = false;
		};
	}, [readOnly, agentId, canEditAgent, langfuseEnabled]);
	const showLangfuseHint =
		!readOnly &&
		langfuseProduction !== null &&
		form.instructions.trim() !== langfuseProduction.trim();

	const setField = <K extends keyof AgentFormState>(
		key: K,
		value: AgentFormState[K],
	) => {
		setForm((prev) => ({ ...prev, [key]: value }));
	};

	const isDirty =
		!readOnly &&
		(isFormDirty(form, initialForm) ||
			imageFile !== null ||
			removeImage ||
			langfuseVersion !== null);
	useUnsavedChangesWarning(isDirty);
	// Read by callbacks that fire after an await (the subagent gate waits for
	// the agents store), so they see the draft as it is then, not at click.
	const isDirtyRef = useRef(isDirty);
	useEffect(() => {
		isDirtyRef.current = isDirty;
	}, [isDirty]);
	const canSave = Boolean(
		form.name.trim() &&
			form.instructions.trim() &&
			(form.visibility !== "teams" || form.teamIds.length > 0),
	);

	const tabs: { key: EditorTab; label: string; alert?: string }[] = [
		{ key: "instructions", label: "Instructions" },
		...(agent && canEditAgent && langfuseEnabled
			? [
					{
						key: "versions" as const,
						label: "Versions",
						alert: showLangfuseHint
							? "Instructions differ from the Langfuse production version"
							: undefined,
					},
				]
			: []),
		{ key: "options", label: "Options" },
		...(agent && canManageAgent
			? [{ key: "permissions" as const, label: "Permissions" }]
			: []),
		...(isMobile ? [{ key: "more" as const, label: "More" }] : []),
	];
	const activeTab = tabs.some((candidate) => candidate.key === tab)
		? tab
		: "instructions";

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
		setField("emoji", emojiData.emoji);
		setShowEmojiPicker(false);
		requestAnimationFrame(() => {
			emojiTriggerRef.current?.focus();
		});
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

			if (
				agent &&
				isAdmin &&
				langfuseVersion &&
				form.instructions.trim() === langfuseVersion.text.trim()
			) {
				await langfuseApi
					.promoteLangfuseVersion(agent.id, langfuseVersion.version)
					.catch((err: unknown) => {
						toast.error(
							getApiErrorMessage(
								err,
								"Saved, but promoting the Langfuse version failed.",
							),
						);
					});
			}

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
			router.push("/agents");
		} catch (err) {
			console.error("Error archiving agent:", err);
			setError(getApiErrorMessage(err, "Failed to archive the agent."));
		}
	};

	const handleToggleDefault = async () => {
		if (!agent) return;
		setIsSettingDefault(true);
		try {
			if (agent.isDefault) {
				await clearDefaultAgent(agent.id);
				toast.success(`${agent.name} is no longer the default agent.`);
			} else {
				await setDefaultAgent(agent.id);
				toast.success(`${agent.name} is now the default agent.`);
			}
		} catch (error: unknown) {
			toast.error(
				getApiErrorMessage(error, "Could not update the default agent."),
			);
		} finally {
			setIsSettingDefault(false);
		}
	};

	const handleDuplicate = async () => {
		if (!agent) return;
		if (
			isDirty &&
			!(await confirmDialog({
				title: "Duplicate the saved agent?",
				description:
					"Your unsaved edits are not part of the saved configuration. Duplicating will leave this draft and copy the last saved version.",
				confirmLabel: "Duplicate saved version",
			}))
		) {
			return;
		}
		try {
			const source = await agentsApi.getAgent(agent.id);
			let created = await createAgent({
				name: `${source.name} copy`,
				instructions: source.instructions ?? "",
				description: source.description ?? null,
				group: source.group ?? null,
				emoji: source.emoji ?? null,
				color: source.color ?? null,
				visibility: source.visibility,
				webSearchEnabled: source.webSearchEnabled ?? false,
				toolDiscoveryMode: source.toolDiscoveryMode ?? "lazy",
				defaultModelId: source.defaultModelId ?? null,
				defaultReasoningEffort: source.defaultReasoningEffort ?? null,
				teamIds: source.teamIds,
				mcpServers: source.mcpServers.map((server) => ({
					mcpServerId: server.mcpServerId,
					enabledByDefault: server.enabledByDefault ?? true,
					tools: server.tools ?? null,
				})),
				sandboxes: (source.sandboxes ?? []).map((sandbox) => ({
					sandboxId: sandbox.sandboxId,
					enabledByDefault: sandbox.enabledByDefault ?? true,
					tools: sandbox.tools,
				})),
				subagentIds: source.subagents.map((subagent) => subagent.id),
				disabledSubagentIdsByDefault: source.subagents
					.filter((subagent) => subagent.enabledByDefault === false)
					.map((subagent) => subagent.id),
				skillIds: (source.skills ?? []).map((skill) => skill.id),
				disabledSkillIdsByDefault: (source.skills ?? [])
					.filter((skill) => skill.enabledByDefault === false)
					.map((skill) => skill.id),
			});
			let imageCopyFailed = false;
			if (source.imageRevision) {
				try {
					const response = await fetch(
						agentsApi.agentImageUrl(source.id, source.imageRevision),
					);
					if (!response.ok) throw new Error("Could not read the agent image.");
					const blob = await response.blob();
					const image = new File([blob], "agent-image", {
						type: blob.type || "image/png",
					});
					const revision = await agentsApi.uploadAgentImage(created.id, image);
					created = { ...created, imageRevision: revision };
					updateAgent(created.id, created);
				} catch {
					imageCopyFailed = true;
				}
			}
			if (imageCopyFailed) {
				toast.warning(
					`Duplicated as “${created.name}”, but its image could not be copied.`,
				);
			} else {
				toast.success(`Duplicated as “${created.name}”.`);
			}
			router.push(`/agents/${created.id}`);
		} catch (error: unknown) {
			toast.error(
				getApiErrorMessage(error, "Could not duplicate the agent."),
			);
		}
	};

	const fieldInputClass =
		"w-full rounded-lg border border-input bg-card px-3 py-[7px] outline-none transition-[border-color,box-shadow] placeholder:text-meta dark:placeholder:text-panel-dim focus:border-petrol focus:shadow-[0_0_0_3px_rgba(22,96,110,0.10)] disabled:cursor-default";

	const capabilityTabs: {
		key: CapabilityTab;
		label: string;
		count?: number;
	}[] = [
		{ key: "mcp", label: "MCP servers", count: form.mcpServers.length },
		{ key: "skills", label: "Skills", count: form.skillIds.length },
		{
			key: "subagents",
			label: "Subagents",
			count: form.subagentIds.length,
		},
		...(agent
			? [
					{
						key: "slack" as const,
						label: "Side channels",
						count: sideChannelCount,
					},
				]
			: []),
		{ key: "sandbox", label: "Sandbox", count: form.sandboxes.length },
	];
	const activeCapabilityTab = capabilityTabs.some(
		(candidate) => candidate.key === capabilityTab,
	)
		? capabilityTab
		: "mcp";

	const renderToolList = (resourceKind: "mcp" | "sandbox") => (
		<AgentToolList
			agentId={agent?.id}
			readOnly={readOnly}
			canEdit={canEditAgent}
			mcpServers={form.mcpServers}
			sandboxes={form.sandboxes}
			resourceKind={resourceKind}
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
						server.mcpServerId === serverId ? { ...server, tools } : server,
					),
				});
			}}
		/>
	);

	const capabilitiesPanel = (
		<div className="flex min-h-0 flex-col">
			<UnderlineTabs
				tabs={capabilityTabs}
				value={activeCapabilityTab}
				onChange={(key) => {
					setCapabilityTab(key);
					onCapabilityTabChange?.(key);
				}}
				className="border-b border-border"
			/>
			<div className="min-h-0 pt-5">
				{activeCapabilityTab === "mcp" && renderToolList("mcp")}
				{activeCapabilityTab === "skills" && (
					<div className="[&>div]:mt-0">
						<AgentSkillList
							readOnly={readOnly}
							skillIds={form.skillIds}
							disabledByDefaultIds={form.disabledSkillIdsByDefault}
							fallbackSkills={agent?.skills ?? []}
							runsCode={form.sandboxes.length > 0}
							onChange={(skillIds) => {
								setForm((current) => ({
									...current,
									skillIds,
									disabledSkillIdsByDefault:
										current.disabledSkillIdsByDefault.filter((id) =>
											skillIds.includes(id),
										),
								}));
							}}
							onDefaultEnabledChange={(skillId, enabled) => {
								setForm((current) => ({
									...current,
									disabledSkillIdsByDefault: enabled
										? current.disabledSkillIdsByDefault.filter(
												(id) => id !== skillId,
											)
										: [
												...new Set([
													...current.disabledSkillIdsByDefault,
													skillId,
												]),
											],
								}));
							}}
							onEnableCodeExecution={() => {
								setCapabilityTab("sandbox");
								onCapabilityTabChange?.("sandbox");
								setAddToolOpen(true);
							}}
						/>
					</div>
				)}
				{activeCapabilityTab === "sandbox" && renderToolList("sandbox")}
				{activeCapabilityTab === "slack" && agent && (
					<div className="[&>section]:mt-0">
						<AgentSideChannelCard
							agentId={agent.id}
							canManage={canManageAgent}
							readOnly={readOnly}
							onCountChange={setSideChannelCount}
						/>
					</div>
				)}
				{activeCapabilityTab === "subagents" && (
					<div className="[&>div]:mt-0">
						<AgentSubagentList
							readOnly={readOnly}
							agentId={agent?.id ?? ""}
							isSubagent={agent?.isSubagent ?? false}
							subagentIds={form.subagentIds}
							disabledByDefaultIds={form.disabledSubagentIdsByDefault}
							fallbackSubagents={agent?.subagents ?? []}
							onChange={(subagentIds) => {
								setForm((current) => ({
									...current,
									subagentIds,
									disabledSubagentIdsByDefault:
										current.disabledSubagentIdsByDefault.filter((id) =>
											subagentIds.includes(id),
										),
								}));
							}}
							onDefaultEnabledChange={(subagentId, enabled) => {
								setForm((current) => ({
									...current,
									disabledSubagentIdsByDefault: enabled
										? current.disabledSubagentIdsByDefault.filter(
												(id) => id !== subagentId,
											)
										: [
												...new Set([
													...current.disabledSubagentIdsByDefault,
													subagentId,
												]),
											],
								}));
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
					</div>
				)}
			</div>
		</div>
	);

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
						<UsageBadge
							dimension="agent"
							id={agent.id}
							title={agent.name}
							variant="header"
							className="hidden lg:flex"
						/>
					)}
					{agent && canSetDefaultAgent && (
						<button
							type="button"
							disabled={isSettingDefault}
							title={
								agent.isDefault
									? "Remove as workspace default"
									: "Set as workspace default"
							}
							onClick={() => {
								void handleToggleDefault();
							}}
							className={cn(
								"inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] border px-3 py-2 text-[13px] font-semibold transition-colors disabled:cursor-default",
								agent.isDefault
									? "border-amber-300/70 bg-amber-50 text-amber-700 dark:border-amber-400/25 dark:bg-amber-400/10 dark:text-amber-300"
									: "border-input bg-card text-foreground hover:border-amber-300 hover:text-amber-700 dark:hover:border-amber-400/30 dark:hover:text-amber-300",
							)}
						>
							<Star
								className="size-3.5"
								fill={agent.isDefault ? "currentColor" : "none"}
							/>
							<span className="hidden lg:inline">
								{isSettingDefault
									? agent.isDefault
										? "Removing…"
										: "Setting…"
									: agent.isDefault
										? "Remove default"
										: "Set default"}
							</span>
						</button>
					)}
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
								{
									label: "Duplicate",
									icon: <Copy />,
									onClick: () => {
										void handleDuplicate();
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
							onKeyDown={(event) => {
								if (event.key !== "Escape" || !showEmojiPicker) return;
								event.preventDefault();
								event.stopPropagation();
								setShowEmojiPicker(false);
								requestAnimationFrame(() => {
									emojiTriggerRef.current?.focus();
								});
							}}
						>
							<button
								ref={emojiTriggerRef}
								type="button"
								disabled={readOnly}
								aria-label={readOnly ? undefined : "Change agent identity"}
								aria-expanded={readOnly ? undefined : showEmojiPicker}
								title={readOnly ? undefined : "Change identity"}
								onKeyDown={(event) => {
									if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
									event.preventDefault();
									setShowEmojiPicker(true);
								}}
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
									role="region"
									aria-label="Change agent identity"
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
										autoFocusSearch
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
								<VisibilityBadge
									visibility={form.visibility}
									teamIds={form.teamIds}
									showTeams
								/>
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
								<VisibilityPicker
									visibility={form.visibility}
									teamIds={form.teamIds}
									onChange={(visibility, teamIds) => {
										setForm((current) => ({
											...current,
											visibility,
											teamIds,
										}));
									}}
								/>
							</div>
						)}
					</div>

					<UnderlineTabs
						tabs={tabs}
						value={activeTab}
						onChange={(key) => {
							setTab(key);
							onTabChange?.(key);
						}}
						className="mt-6 border-b border-border"
					/>

					{/* The active tab fills the remaining panel height. */}
					<div className="flex min-h-0 flex-1 flex-col pt-5">
						{activeTab === "instructions" &&
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
						{activeTab === "instructions" && showLangfuseHint && (
							<p className="mt-2 text-[12px] text-meta dark:text-panel-dim">
								These instructions differ from the Langfuse production
								version. See the{" "}
								<button
									type="button"
									onClick={() => {
										setTab("versions");
										onTabChange?.("versions");
									}}
									className="cursor-pointer font-semibold text-petrol hover:underline"
								>
									Versions
								</button>{" "}
								tab.
							</p>
						)}
						{activeTab === "versions" && agent && (
							<AgentLangfusePanel
								agentId={agent.id}
								agentName={agent.name}
								readOnly={readOnly}
								isWorkspaceAdmin={isAdmin}
								pickedVersion={langfuseVersion?.version ?? null}
								hasUnsavedEdits={
									form.instructions !==
									(langfuseVersion?.text ?? initialForm.instructions)
								}
								onPick={(version) => {
									setLangfuseVersion(version);
									setField("instructions", version.text);
								}}
							/>
						)}
						{activeTab === "permissions" && agent && canManageAgent && (
							<AgentPermissionsPanel
								agentId={agent.id}
								ownerId={agent.ownerId}
							/>
						)}

						{activeTab === "options" &&
							(readOnly ? (
								<div className="w-full max-w-2xl">
									<h2 className="text-[14px] font-semibold text-foreground">
										Conversation defaults
									</h2>
									<p className="mt-1 text-[11.5px] leading-relaxed text-meta dark:text-panel-dim">
										Applied automatically when a conversation starts with
										this agent.
									</p>
									<dl className="mt-4 overflow-hidden rounded-xl border border-border bg-card">
										<div className="flex items-center gap-6 px-4 py-3.5">
											<div className="min-w-0 flex-1">
												<dt className="text-[12.5px] font-semibold text-foreground">
													Default model
													<span className="mt-0.5 block text-[10.5px] font-normal text-meta dark:text-panel-dim">
														Used for new conversations.
													</span>
												</dt>
											</div>
											<dd className="max-w-[55%] truncate rounded-full bg-hover px-3 py-1.5 text-[11.5px] font-semibold text-foreground dark:bg-white/5">
												{selectedDefaultModel?.name ??
													form.defaultModelId ??
													"Workspace default"}
											</dd>
										</div>
										<div className="flex items-center gap-6 border-t border-hairline px-4 py-3.5 dark:border-white/5">
											<div className="min-w-0 flex-1">
												<dt className="text-[12.5px] font-semibold text-foreground">
													Reasoning effort
													<span className="mt-0.5 block text-[10.5px] font-normal text-meta dark:text-panel-dim">
														Controls how deeply the model reasons.
													</span>
												</dt>
											</div>
											<dd className="max-w-[55%] truncate rounded-full bg-hover px-3 py-1.5 text-[11.5px] font-semibold text-foreground dark:bg-white/5">
												{form.defaultModelId
													? validatedDefaultEffort
														? effortLabel(validatedDefaultEffort)
														: defaultEffortLabel
													: "Workspace default"}
											</dd>
										</div>
										<div className="flex items-center gap-6 border-t border-hairline px-4 py-3.5 dark:border-white/5">
											<div className="min-w-0 flex-1">
												<dt className="text-[12.5px] font-semibold text-foreground">
													Web search
													<span className="mt-0.5 block text-[10.5px] font-normal text-meta dark:text-panel-dim">
														Native search from the selected model provider.
													</span>
												</dt>
											</div>
											<dd
												className={cn(
													"rounded-full px-3 py-1.5 text-[11.5px] font-semibold",
													form.webSearchEnabled
														? "bg-success-bg text-success"
														: "bg-hover text-meta dark:bg-white/5 dark:text-panel-dim",
												)}
											>
												{form.webSearchEnabled ? "Enabled" : "Disabled"}
											</dd>
										</div>
										<div className="flex items-center gap-6 border-t border-hairline px-4 py-3.5 dark:border-white/5">
											<div className="min-w-0 flex-1">
												<dt className="text-[12.5px] font-semibold text-foreground">
													AI tool discovery
													<span className="mt-0.5 block text-[10.5px] font-normal text-meta dark:text-panel-dim">
														Loads relevant tool schemas on demand.
													</span>
												</dt>
											</div>
											<dd
												className={cn(
													"rounded-full px-3 py-1.5 text-[11.5px] font-semibold",
													form.toolDiscoveryMode !== "disabled"
														? "bg-success-bg text-success"
														: "bg-hover text-meta dark:bg-white/5 dark:text-panel-dim",
												)}
											>
												{TOOL_DISCOVERY_LABELS[form.toolDiscoveryMode]}
											</dd>
										</div>
									</dl>
								</div>
							) : (
						<div className="flex flex-col gap-3">
						<div className="overflow-hidden rounded-xl border border-border bg-card">
							<div className="flex items-start gap-3 px-4 py-3.5">
								<div className="min-w-0 flex-1">
									<p className="text-[13px] font-semibold text-foreground">
										Default model
									</p>
									<p className="mt-0.5 text-[11.5px] leading-[1.45] text-meta dark:text-panel-dim">
										Preselected when a conversation starts with this agent.
									</p>
								</div>
								<div className="flex shrink-0 flex-col items-end gap-1.5">
									<ModelPickerChip
										value={form.defaultModelId}
										disabled={readOnly || !canEditAgent}
										emptyLabel="Workspace default"
										onChange={(modelId) => {
											setForm((current) =>
												current.defaultModelId === modelId
													? current
													: {
															...current,
															defaultModelId: modelId,
															defaultReasoningEffort: null,
														},
											);
										}}
									/>
									{form.defaultModelId && !readOnly && canEditAgent && (
										<button
											type="button"
											onClick={() => {
												setForm((current) => ({
													...current,
													defaultModelId: null,
													defaultReasoningEffort: null,
												}));
											}}
											className="cursor-pointer px-1 text-[10.5px] font-medium text-meta transition-colors hover:text-petrol dark:text-panel-dim dark:hover:text-panel-terminal"
										>
											Use workspace default
										</button>
									)}
								</div>
							</div>
							<div className="flex items-center gap-3 border-t border-hairline px-4 py-3 dark:border-white/5">
								<div className="min-w-0 flex-1">
									<p className="text-[12px] font-semibold text-foreground">
										Reasoning effort
									</p>
									<p className="mt-0.5 text-[10.5px] text-meta dark:text-panel-dim">
										Applied with the agent&apos;s default model.
									</p>
								</div>
								{form.defaultModelId &&
								effortLevels.length > 0 &&
								!readOnly &&
								canEditAgent ? (
									<DropdownMenu
										align="end"
										side="top"
										className="[&_[role=menuitem]+[role=menuitem]]:mt-0.5"
										items={[
											{
												label: selectedDefaultModel?.reasoningEffortDefault
													? `Default (${effortLabel(selectedDefaultModel.reasoningEffortDefault)})`
													: "Auto",
												active: !validatedDefaultEffort,
												onClick: () => {
													setField("defaultReasoningEffort", null);
												},
											},
											...effortLevels.map((level) => ({
												label: effortLabel(level),
												active: validatedDefaultEffort === level,
												onClick: () => {
													setField("defaultReasoningEffort", level);
												},
											})),
										]}
										trigger={
											<button
												type="button"
												className="inline-flex h-8 cursor-pointer items-center gap-1.5 rounded-full bg-hover px-3 text-[12px] font-medium text-foreground transition-colors hover:bg-petrol-tint dark:bg-white/5 dark:hover:bg-white/10"
											>
												{defaultEffortLabel}
											</button>
										}
									/>
								) : (
									<span className="inline-flex h-8 items-center rounded-full bg-hover px-3 text-[12px] font-medium text-meta dark:bg-white/5 dark:text-panel-dim">
										{form.defaultModelId
											? validatedDefaultEffort
												? effortLabel(validatedDefaultEffort)
												: defaultEffortLabel
											: "Workspace default"}
									</span>
								)}
							</div>
						</div>
						<div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3">
							<div className="min-w-0 flex-1">
								<p className="text-[13px] font-semibold text-foreground">
									Web search
								</p>
								<p className="mt-0.5 text-[11.5px] leading-[1.45] text-meta dark:text-panel-dim">
									Uses the selected model provider&apos;s native search when
									available. No MCP server required.
								</p>
							</div>
							<Switch
								aria-label="Enable native web search"
								checked={form.webSearchEnabled}
								disabled={readOnly || !canEditAgent}
								onCheckedChange={(checked) => {
									setField("webSearchEnabled", checked);
								}}
							/>
						</div>
						<div className="flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3">
							<div className="min-w-0 flex-1">
								<p className="text-[13px] font-semibold text-foreground">
									AI tool discovery
								</p>
								<p className="mt-0.5 text-[11.5px] leading-[1.45] text-meta dark:text-panel-dim">
									Finds relevant MCP tools before loading their full schemas.
									All enabled tools remain discoverable.
								</p>
							</div>
							<DropdownMenu
								align="end"
								side="top"
								itemClassName="py-[9px]"
								items={[
									{
										label: "Eager",
										description: "load every MCP schema",
										active: form.toolDiscoveryMode === "disabled",
										onClick: () => {
											setField("toolDiscoveryMode", "disabled");
										},
									},
									{
										label: "Lazy",
										description: "choose servers per prompt",
										active: form.toolDiscoveryMode === "lazy",
										onClick: () => {
											setField("toolDiscoveryMode", "lazy");
										},
									},
									{
										label: "Precision",
										description: "retrieve tools adaptively",
										active: form.toolDiscoveryMode === "local",
										onClick: () => {
											setField("toolDiscoveryMode", "local");
										},
									},
								]}
								trigger={
									<button
										type="button"
										disabled={readOnly || !canEditAgent}
										className="inline-flex h-8 cursor-pointer items-center rounded-full bg-hover px-3 text-[12px] font-medium text-foreground transition-colors hover:bg-petrol-tint disabled:cursor-not-allowed disabled:opacity-60 dark:bg-white/5 dark:hover:bg-white/10"
									>
										{TOOL_DISCOVERY_LABELS[form.toolDiscoveryMode]}
									</button>
								}
							/>
						</div>
						</div>
							))}
						{activeTab === "more" && isMobile && (
							<div className="flex min-w-0 flex-col">
								{capabilitiesPanel}
							</div>
						)}
					</div>
				</div>

				{/* Right: capabilities */}
				{!isMobile && (
					<div className="hidden min-w-0 overflow-y-auto bg-sidebar p-7 md:block md:flex-1 dark:bg-white/[0.02] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
						{capabilitiesPanel}
					</div>
				)}
			</div>
		</div>
	);
}

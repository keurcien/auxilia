"use client";

import {
	type PointerEvent as ReactPointerEvent,
	useCallback,
	useEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
	type PromptInputMessage,
	usePromptInputController,
} from "@/components/ai-elements/prompt-input";
import ChatPromptInput from "./components/prompt-input";
import { SelectAgentDialog } from "./components/select-agent-dialog";
import { useThreadsStore } from "@/stores/threads-store";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useModelsStore } from "@/stores/models-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useAgentsStore } from "@/stores/agents-store";
import * as agentsApi from "@/lib/api/resources/agents";
import * as threadsApi from "@/lib/api/resources/threads";
import { generateUuid } from "@/lib/utils/uuid";
import { ChevronDown, Loader2 } from "lucide-react";
import { Agent } from "@/types/agents";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { getDefaultModel } from "@/lib/utils/get-default-model";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import type { ThreadResourceSettings } from "@/types/threads";
import { toast } from "sonner";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	ChatHeaderActions,
	ChatMemoryToggle,
} from "@/components/layout/chat-header";

const EMPTY_RESOURCE_SETTINGS: ThreadResourceSettings = {
	toolMode: null,
	disabledMcpServerIds: [],
	disabledSkillIds: [],
	disabledSandboxIds: [],
	disabledSubagentIds: [],
};

const AVATAR_SWIPE_THRESHOLD = 28;
const AVATAR_SWIPE_LIMIT = 44;

const StarterChatPage = () => {
	const params = useParams();
	const router = useRouter();
	const searchParams = useSearchParams();
	const agentId = params.id as string;
	const projectId = searchParams.get("projectId");
	const folderId = projectId ? searchParams.get("folderId") : null;
	const [isCreating, setIsCreating] = useState(false);
	const [memoriesEnabled, setMemoriesEnabled] = useState(true);
	const { modelSelection, starterAgent } = usePromptInputController();
	const setStarterAgent = starterAgent.set;
	const selectedModel = modelSelection.value;
	const setSelectedModel = modelSelection.setModel;
	// Reasoning-effort choice for the selected model; null = the model's
	// default. Pinned onto the thread at creation, like the model.
	const [reasoningEffort, setReasoningEffort] = useState<string | null>(null);
	const [resourceSettingsState, setResourceSettingsState] = useState<{
		agentId: string | null;
		settings: ThreadResourceSettings;
	}>({ agentId: null, settings: EMPTY_RESOURCE_SETTINGS });
	const resourceSettings =
		resourceSettingsState.agentId === agentId
			? resourceSettingsState.settings
			: EMPTY_RESOURCE_SETTINGS;
	const addThread = useThreadsStore((state) => state.addThread);
	const agents = useAgentsStore((state) => state.agents);
	const agentsInitialized = useAgentsStore((state) => state.isInitialized);
	const fetchAgents = useAgentsStore((state) => state.fetchAgents);
	const models = useModelsStore((state) => state.models);
	const fetchModels = useModelsStore((state) => state.fetchModels);
	const [agent, setAgent] = useState<Agent | null>(null);
	const [agentPreview, setAgentPreview] = useState<Agent | null>(null);
	const [loadedAgentId, setLoadedAgentId] = useState<string | null>(null);
	const [isAgentDialogOpen, setIsAgentDialogOpen] = useState(false);
	const [avatarDragOffset, setAvatarDragOffset] = useState(0);
	const [avatarDragging, setAvatarDragging] = useState(false);
	const avatarGestureRef = useRef<{
		pointerId: number;
		startX: number;
		startY: number;
	} | null>(null);
	const suppressAvatarClickRef = useRef(false);
	const agentRequestIdRef = useRef(0);
	const defaultsAppliedAgentIdRef = useRef<string | null>(null);
	const currentAgent = loadedAgentId === agentId ? agent : null;
	const headerAgent = currentAgent ?? (agentPreview?.id === agentId ? agentPreview : null);
	const availableAgents = useMemo(
		() =>
			agents.filter(
				(candidate) => !candidate.isArchived && candidate.currentUserPermission !== null,
			),
		[agents],
	);
	const {
		ready: agentReady,
		acceptsFiles,
		status,
		detail: statusDetail,
		disconnectedMcpServers,
		refetch: refetchReady,
	} = useAgentReadiness(agentId, resourceSettings);

	const switchAgent = useCallback(
		(step: -1 | 1) => {
			if (isCreating || availableAgents.length < 2) return false;
			const currentIndex = availableAgents.findIndex((candidate) => candidate.id === agentId);
			if (currentIndex < 0) return false;
			const target =
				availableAgents[
					(currentIndex + step + availableAgents.length) % availableAgents.length
				];
			if (!target || target.id === agentId) return false;

			suppressAvatarClickRef.current = true;
			setAgentPreview(target);
			setStarterAgent({
				name: target.name,
				emoji: target.emoji ?? null,
			});
			const query = searchParams.toString();
			router.replace(`/agents/${target.id}/chat${query ? `?${query}` : ""}`);
			return true;
		},
		[agentId, availableAgents, isCreating, router, searchParams, setStarterAgent],
	);

	const resetAvatarGesture = useCallback(() => {
		avatarGestureRef.current = null;
		setAvatarDragging(false);
		setAvatarDragOffset(0);
	}, []);

	const handleAvatarPointerDown = (event: ReactPointerEvent<HTMLButtonElement>) => {
		if (event.button !== 0 || isCreating || availableAgents.length < 2) {
			return;
		}
		event.currentTarget.setPointerCapture(event.pointerId);
		avatarGestureRef.current = {
			pointerId: event.pointerId,
			startX: event.clientX,
			startY: event.clientY,
		};
		setAvatarDragging(true);
	};

	const handleAvatarPointerMove = (event: ReactPointerEvent<HTMLButtonElement>) => {
		const gesture = avatarGestureRef.current;
		if (gesture?.pointerId !== event.pointerId) return;
		const deltaY = event.clientY - gesture.startY;
		const deltaX = event.clientX - gesture.startX;
		if (Math.abs(deltaY) <= Math.abs(deltaX)) return;
		setAvatarDragOffset(Math.max(-AVATAR_SWIPE_LIMIT, Math.min(AVATAR_SWIPE_LIMIT, deltaY)));
	};

	const handleAvatarPointerUp = (event: ReactPointerEvent<HTMLButtonElement>) => {
		const gesture = avatarGestureRef.current;
		if (gesture?.pointerId !== event.pointerId) return;
		const deltaY = event.clientY - gesture.startY;
		const deltaX = event.clientX - gesture.startX;
		const switched =
			Math.abs(deltaY) >= AVATAR_SWIPE_THRESHOLD &&
			Math.abs(deltaY) > Math.abs(deltaX) &&
			switchAgent(deltaY < 0 ? 1 : -1);
		resetAvatarGesture();
		if (switched) {
			window.setTimeout(() => {
				suppressAvatarClickRef.current = false;
			}, 250);
		}
	};

	const handleSubmit = async (message: PromptInputMessage) => {
		if (!message) return;

		const hasText = "text" in message && message.text?.trim();
		const hasFiles =
			"files" in message && message.files && message.files.length > 0;

		if (!hasText && !hasFiles) {
			return;
		}

		const modelId = selectedModel ?? getDefaultModel(models);
		if (!modelId) {
			console.error("No model available to create thread");
			return;
		}

		setIsCreating(true);
		const submittedAgentId = agentId;
		const submittedAgent = currentAgent;
		const submittedAgentRequestId = agentRequestIdRef.current;
		const submittedResourceSettings =
			resourceSettingsState.agentId === submittedAgentId
				? resourceSettingsState.settings
				: null;
		const threadId = generateUuid();

		try {
			const includeImages =
				models.find((model) => model.id === modelId)?.multimodal !== false;
			const created = await threadsApi.startThread(
				{
					id: threadId,
					agentId: submittedAgentId,
					modelId,
					reasoningEffort,
					memoriesEnabled,
					projectId,
					folderId,
					...(submittedResourceSettings ?? {}),
				},
				message,
				includeImages,
				acceptsFiles === true,
			);
			if (agentRequestIdRef.current !== submittedAgentRequestId) {
				setIsCreating(false);
				const error = new Error("Conversation creation was superseded");
				error.name = "AbortError";
				throw error;
			}

			const thread = {
				...created,
				agentName: submittedAgent?.name ?? null,
				agentEmoji: submittedAgent?.emoji ?? null,
				agentColor: submittedAgent?.color ?? null,
				agentImageRevision: submittedAgent?.imageRevision ?? null,
			};

			addThread(thread);
			usePendingMessageStore
				.getState()
				.setOptimisticMessage(threadId, message);
			useActiveRunsStore.getState().markThreadRunning(threadId);

			router.push(`/agents/${submittedAgentId}/chat/${threadId}`);
		} catch (error) {
			setIsCreating(false);
			const aborted = error instanceof Error && error.name === "AbortError";
			if (!aborted) {
				console.error("Error creating thread:", error);
				toast.error(
					getApiErrorMessage(
						error,
						"Could not start the conversation. Try again.",
					),
				);
			}
			throw error;
		}
	};

	useEffect(() => {
		if (models.length === 0) {
			fetchModels().catch((error) => {
				console.error("Error fetching models:", error);
			});
		}
	}, [fetchModels, models.length]);

	useEffect(() => {
		if (!agentsInitialized) {
			void fetchAgents().catch(() => {});
		}
	}, [agentsInitialized, fetchAgents]);

	useEffect(() => {
		resetAvatarGesture();
	}, [agentId, resetAvatarGesture]);

	useEffect(() => {
		if (
			currentAgent === null ||
			models.length === 0 ||
			defaultsAppliedAgentIdRef.current === agentId
		) {
			return;
		}
		const configuredModel = currentAgent.defaultModelId
			? models.find((model) => model.id === currentAgent.defaultModelId)
			: undefined;
		const modelId = configuredModel?.id ?? getDefaultModel(models);
		if (!modelId) return;

		defaultsAppliedAgentIdRef.current = agentId;
		let cancelled = false;
		queueMicrotask(() => {
			if (cancelled) return;
			setSelectedModel(modelId);
			setReasoningEffort(
				configuredModel &&
					currentAgent.defaultReasoningEffort &&
					configuredModel.reasoningEffortLevels.includes(
						currentAgent.defaultReasoningEffort,
					)
					? currentAgent.defaultReasoningEffort
					: null,
			);
		});
		return () => {
			cancelled = true;
		};
	}, [agentId, currentAgent, models, setSelectedModel]);

	useEffect(() => {
		const requestId = ++agentRequestIdRef.current;
		const fetchAgent = async () => {
			try {
				const [fetchedAgent, resources] = await Promise.all([
					agentsApi.getAgent(agentId),
					agentsApi.getAgentResources(agentId),
				]);
				if (requestId !== agentRequestIdRef.current) return;
				setAgent(fetchedAgent);
				setLoadedAgentId(agentId);
				setAgentPreview(null);
				setResourceSettingsState((current) =>
					current.agentId === agentId
						? current
						: {
								agentId,
								settings: {
									...EMPTY_RESOURCE_SETTINGS,
									disabledMcpServerIds: resources.mcpServers
										.filter((server) => !server.enabledByDefault)
										.map((server) => server.id),
									disabledSkillIds: resources.skills
										.filter((skill) => skill.enabledByDefault === false)
										.map((skill) => skill.id),
									disabledSandboxIds: resources.sandboxes
										.filter((sandbox) => !sandbox.enabledByDefault)
										.map((sandbox) => sandbox.id),
									disabledSubagentIds: resources.subagents
										.filter((subagent) => subagent.enabledByDefault === false)
										.map((subagent) => subagent.id),
								},
							},
				);
				setStarterAgent({
					name: fetchedAgent.name,
					emoji: fetchedAgent.emoji ?? null,
				});
			} catch (error) {
				if (requestId === agentRequestIdRef.current) {
					console.error("Error fetching agent:", error);
				}
			}
		};
		void fetchAgent();
		return () => {
			agentRequestIdRef.current += 1;
		};
	}, [agentId, setStarterAgent]);

	return (
		<>
			<ChatHeaderActions>
				<ChatMemoryToggle
					enabled={memoriesEnabled}
					saving={isCreating}
					onChange={setMemoriesEnabled}
				/>
			</ChatHeaderActions>
		<div className="container mx-auto h-full flex flex-col items-center justify-center max-w-4xl px-6">
			<div className="w-full max-w-3xl space-y-8">
				<div className="text-center space-y-4">
					{headerAgent ? (
						<div className="mx-auto flex items-center justify-center gap-2">
							<button
								type="button"
								aria-label={`Choose agent. Swipe up for the next agent or down for the previous agent. Current agent: ${headerAgent.name}`}
								title="Swipe up or down to switch agents"
								onClick={() => {
									if (suppressAvatarClickRef.current) return;
									setIsAgentDialogOpen(true);
								}}
								onPointerDown={handleAvatarPointerDown}
								onPointerMove={handleAvatarPointerMove}
								onPointerUp={handleAvatarPointerUp}
								onPointerCancel={resetAvatarGesture}
								className="touch-none cursor-grab rounded-full outline-none transition-opacity hover:opacity-80 focus-visible:ring-2 focus-visible:ring-petrol/40 active:cursor-grabbing"
							>
								<span
									className={
										avatarDragging
											? "block"
											: "block transition-transform duration-200 ease-out"
									}
									style={{
										transform: `translate3d(0, ${avatarDragOffset}px, 0) scale(${1 - Math.min(Math.abs(avatarDragOffset), AVATAR_SWIPE_LIMIT) / 440})`,
									}}
								>
									<AgentAvatar
										agentId={headerAgent.id}
										name={headerAgent.name}
										imageRevision={headerAgent.imageRevision}
										color={headerAgent.color}
										emoji={headerAgent.emoji}
										size="lg"
									/>
								</span>
							</button>
							<button
								type="button"
								onClick={() => {
									setIsAgentDialogOpen(true);
								}}
								className="flex cursor-pointer items-center gap-2 transition-opacity hover:opacity-80"
							>
								<h1 className="text-4xl font-bold">{headerAgent.name}</h1>
								<ChevronDown className="ml-8 mt-1 size-5 text-muted-foreground" />
							</button>
						</div>
					) : (
						<div
							className="mx-auto flex h-[52px] items-center justify-center"
							role="status"
							aria-label="Loading agent"
						>
							<Loader2
								className="size-7 animate-spin text-petrol"
								aria-hidden="true"
							/>
						</div>
					)}
					{status !== "sandbox_unavailable" && (
						<p className="text-lg text-muted-foreground">
							Ask me anything to begin
						</p>
					)}
				</div>

				<div className="w-full">
					{status === "sandbox_unavailable" ? (
						<div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
							<p className="flex-1 text-sm text-muted-foreground">
								{statusDetail ?? "This agent's sandbox is not available right now."}{" "}
								Try again in a moment, or ask a workspace admin.
							</p>
							<button
								type="button"
								className="shrink-0 cursor-pointer rounded-[7px] border border-input bg-card px-3 py-1.5 text-[12.5px] font-semibold text-foreground transition-colors hover:border-border-hover"
								onClick={() => {
									refetchReady();
								}}
							>
								Check again
							</button>
						</div>
					) : (
						<ChatPromptInput
							agentId={agentId}
							draftKey={`new:${agentId}`}
							onSubmit={handleSubmit}
							status={isCreating ? "streaming" : "ready"}
							className="w-full"
							selectedModel={selectedModel}
							onModelChange={(modelId) => {
								setSelectedModel(modelId);
								// Levels differ per model — a carried-over choice could be
								// one the new model rejects.
								setReasoningEffort(null);
							}}
							selectedEffort={reasoningEffort}
							onEffortChange={setReasoningEffort}
							agentReady={agentReady}
							acceptsFiles={acceptsFiles}
							disconnectedServers={disconnectedMcpServers}
							onAllConnected={() => {
								refetchReady();
							}}
							resourceSettings={resourceSettings}
							onResourceSettingsChange={(settings) => {
								setResourceSettingsState({ agentId, settings });
							}}
						/>
					)}
				</div>

				<SelectAgentDialog
					open={isAgentDialogOpen}
					onOpenChange={setIsAgentDialogOpen}
					onAgentSelect={(a) => {
						setStarterAgent({ name: a.name, emoji: a.emoji ?? null });
					}}
				/>
			</div>
		</div>
		</>
	);
};

export default StarterChatPage;

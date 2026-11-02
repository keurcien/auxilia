"use client";

import { cn } from "@/lib/utils";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
import { handleKeyboardListNavigation } from "@/lib/keyboard-list-navigation";
import {
	PromptInput,
	PromptInputAddAttachmentButton,
	PromptInputAttachment,
	PromptInputAttachments,
	PromptInputBody,
	PromptInputButton,
	PromptInputFooter,
	type PromptInputMessage,
	PromptInputTextarea,
	PromptInputTools,
	usePromptInputController,
	usePromptInputDraft,
} from "@/components/ai-elements/prompt-input";
import type { BaseMessage } from "@langchain/core/messages";
import {
	isAIMessage,
	isHumanMessage,
	isToolMessage,
} from "@langchain/core/messages";
import {
	BrainIcon,
	ChartNoAxesColumnIncreasingIcon,
	CheckIcon,
	CpuIcon,
	Loader2,
	PlugIcon,
	XIcon,
} from "lucide-react";
import {
	useEffect,
	useLayoutEffect,
	useMemo,
	useRef,
	useState,
} from "react";
import { toast } from "sonner";
import { DropdownMenu } from "@/components/ui/dropdown-menu";
import { useMcpOAuth } from "@/components/providers/mcp-oauth-provider";
import { useModelsStore } from "@/stores/models-store";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { Model } from "@/types/models";
import { MCPServer } from "@/types/mcp-servers";
import { ConnectServersDialog } from "./connect-servers-dialog";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogTitle,
	DialogTrigger,
} from "@/components/ui/dialog";
import { SearchBar } from "@/components/ui/search-bar";
import { getApiErrorMessage, toApiError } from "@/lib/api/errors";
import * as agentsApi from "@/lib/api/resources/agents";
import type { ToolDiscoveryMode } from "@/types/agents";
import type { QueuedPrompt } from "@/types/runs";
import type {
	ThreadResourceSettings,
	ThreadToolMode,
} from "@/types/threads";
import { PromptQueue } from "./prompt-queue";

// Petrol Mono composer pills: 34px tall, 999px radius, on the hover tint.
const composerPillClass = cn(
	"h-[34px] max-w-full shrink-0 whitespace-nowrap px-3 gap-2 rounded-full",
	"text-[13px] font-medium text-foreground",
	"bg-hover dark:bg-white/5",
	"hover:bg-petrol-tint dark:hover:bg-white/10",
	"data-[state=open]:bg-petrol-tint dark:data-[state=open]:bg-white/10",
	"disabled:opacity-60 disabled:cursor-not-allowed",
	"transition-colors",
);

const composerMenuClass =
	"max-h-[min(420px,calc(100dvh-2rem))] w-[360px] max-w-[calc(100vw-2rem)] overflow-y-auto";

const STATS_LOADER_MIN_MS = 400;
const THREAD_TOOL_MODE_LABELS: Record<ThreadToolMode, string> = {
	no_tools: "No tools",
	eager: "Eager",
	lazy: "Lazy",
	precision: "Precision",
	force_all: "Force all",
};
const AGENT_DISCOVERY_TO_THREAD_MODE: Record<
	ToolDiscoveryMode,
	Exclude<ThreadToolMode, "no_tools" | "force_all">
> = {
	disabled: "eager",
	lazy: "lazy",
	local: "precision",
};

interface ChatPromptInputProps {
	agentId: string;
	draftKey: string;
	onSubmit: (message: PromptInputMessage) => void | Promise<void>;
	status: "submitted" | "streaming" | "ready" | "error";
	queueMode?: boolean;
	className?: string;
	stop?: () => void;
	stopping?: boolean;
	onModelChange?: (modelId: string) => void | Promise<void>;
	selectedModel?: string;
	readOnlyModel?: boolean;
	modelChangeDisabled?: boolean;
	readOnlyEffort?: boolean;
	// Reasoning-effort choice for the selected model; null = the model's default.
	selectedEffort?: string | null;
	// May persist (thread page): the pill shows a pending state and a failure
	// toasts instead of leaving the UI out of sync with the server.
	onEffortChange?: (effort: string | null) => void | Promise<void>;
	agentReady?: boolean | null;
	acceptsFiles?: boolean | null;
	disconnectedServers?: MCPServer[];
	onAllConnected?: () => void;
	resourceSettings: ThreadResourceSettings;
	onResourceSettingsChange: (settings: ThreadResourceSettings) => void;
	resourceSettingsSaving?: boolean;
	queuedPrompts?: QueuedPrompt[];
	onEnqueue?: (message: PromptInputMessage) => Promise<void>;
	onUpdateQueued?: (id: string, text: string) => Promise<void>;
	onBeginQueuedEdit?: (id: string) => Promise<void>;
	onEndQueuedEdit?: (id: string) => Promise<void>;
	onSendQueuedNow?: (id: string) => Promise<void>;
	sendQueuedNowDisabled?: boolean;
	onRemoveQueued?: (id: string) => Promise<void>;
	onReorderQueued?: (orderedIds: string[]) => Promise<void>;
	queueLoading?: boolean;
	onQueueAuthorizationRequired?: () => void;
	submissionDisabled?: boolean;
	completed?: boolean;
	reopening?: boolean;
	onReopen?: () => void;
	conversationMessages?: BaseMessage[];
	loadLatestConversationMessages?: () => Promise<BaseMessage[]>;
}

// Human labels for the canonical effort ladder ("none" reads as Off — it
// turns the model's thinking off entirely).
const EFFORT_LABELS = new Map<string, string>([
	["none", "Off"],
	["minimal", "Minimal"],
	["low", "Low"],
	["medium", "Medium"],
	["high", "High"],
	["xhigh", "Extra high"],
	["max", "Max"],
]);

const effortLabel = (effort: string) => EFFORT_LABELS.get(effort) ?? effort;

const safeHttpUrl = (value: unknown): string | null => {
	if (typeof value !== "string") return null;
	try {
		const url = new URL(value);
		return url.protocol === "http:" || url.protocol === "https:"
			? url.toString()
			: null;
	} catch {
		return null;
	}
};

const ChatPromptInput = ({
	agentId,
	draftKey,
	onSubmit,
	status,
	queueMode = false,
	className,
	stop,
	stopping = false,
	onModelChange,
	selectedModel: externalSelectedModel,
	readOnlyModel = false,
	modelChangeDisabled = false,
	readOnlyEffort = readOnlyModel,
	selectedEffort = null,
	onEffortChange,
	agentReady,
	acceptsFiles = null,
	disconnectedServers = [],
	onAllConnected,
	resourceSettings,
	onResourceSettingsChange,
	resourceSettingsSaving = false,
	queuedPrompts = [],
	onEnqueue,
	onUpdateQueued,
	onBeginQueuedEdit,
	onEndQueuedEdit,
	onSendQueuedNow,
	sendQueuedNowDisabled = false,
	onRemoveQueued,
	onReorderQueued,
	queueLoading = false,
	onQueueAuthorizationRequired,
	submissionDisabled = false,
	completed = false,
	reopening = false,
	onReopen,
	conversationMessages,
	loadLatestConversationMessages,
}: ChatPromptInputProps) => {
	usePromptInputDraft(draftKey);
	const { startAuthorization } = useMcpOAuth();
	const [connectDialogOpen, setConnectDialogOpen] = useState(false);
	const models = useModelsStore((state) => state.models);
	const fetchModels = useModelsStore((state) => state.fetchModels);
	const agentName = useChatHeaderStore((state) => state.agentName);
	const [model, setModel] = useState<string | undefined>(undefined);
	const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
	const [modelSearch, setModelSearch] = useState("");
	const [modelUpdatePending, setModelUpdatePending] = useState(false);
	const [effortUpdatePending, setEffortUpdatePending] = useState(false);
	const textareaRef = useRef<HTMLTextAreaElement>(null);
	const initialFocusPendingRef = useRef(true);
	const wasCompletedRef = useRef(completed);
	const controller = usePromptInputController();
	const setThreadDraft = controller.textInput.setDraft;
	const mountedRef = useRef(true);
	const activeDraftKeyRef = useRef(draftKey);
	activeDraftKeyRef.current = draftKey;
	const [editingId, setEditingId] = useState<string | null>(null);
	const [busyId, setBusyId] = useState<string | null>(null);
	const [statsDialogOpen, setStatsDialogOpen] = useState(false);
	const [statsLoading, setStatsLoading] = useState(false);
	const [statsMessages, setStatsMessages] = useState<BaseMessage[] | null>(null);
	const statsRequestRef = useRef(0);
	const [toolDiscoveryConfig, setToolDiscoveryConfig] = useState<{
		agentId: string;
		mode: ToolDiscoveryMode;
	} | null>(null);
	// A direct `onSubmit` (the protocol stream's `submit`) must only happen
	// while the server has no run on the thread: it shows the message
	// optimistically, and if a run is active the server parks it in the
	// queue instead — the prompt then appears in the conversation *and* in
	// the queue. The `queueMode` prop lags a render or two behind the first
	// send, so this lock is held for the whole run (the stream resolves only
	// once the run ends). The stream must still carry the first prompt of
	// an idle thread: that is what attaches it to the thread's events.
	const directRunLockRef = useRef(false);
	const [preparingSubmission, setPreparingSubmission] = useState(false);
	const configurationLocked = modelChangeDisabled || preparingSubmission;
	const draftRef = useRef<string | null>(null);
	const effectiveEditingId =
		editingId && queuedPrompts.some((item) => item.id === editingId)
			? editingId
			: null;
	const agentToolDiscoveryMode =
		toolDiscoveryConfig?.agentId === agentId
			? toolDiscoveryConfig.mode
			: null;
	const agentDefaultThreadToolMode = agentToolDiscoveryMode
		? AGENT_DISCOVERY_TO_THREAD_MODE[agentToolDiscoveryMode]
		: null;
	const effectiveThreadToolMode =
		resourceSettings.toolMode ?? agentDefaultThreadToolMode;
	// A resume rebuilds the graph from the thread. Changing its tool surface
	// while a run/HITL is active could remove the very tool being resumed.
	const canChangeToolMode = !readOnlyModel && !configurationLocked;

	const currentModel = externalSelectedModel ?? model;
	const selectedModelData = models.find((m) => m.id === currentModel);
	const effortLevels = selectedModelData?.reasoningEffortLevels ?? [];
	const effortDefault = selectedModelData?.reasoningEffortDefault ?? null;
	// A stored effort the catalog no longer declares is clamped to the model
	// default at run time — don't display it as if it were in effect. When the
	// model itself is unknown (e.g. disabled, absent from the picker list) the
	// levels can't be checked, so trust the stored value.
	const validatedEffort =
		selectedEffort &&
		(selectedModelData === undefined || effortLevels.includes(selectedEffort))
			? selectedEffort
			: null;
	// Pill label: the explicit choice, else the model's declared default
	// level, else Auto (provider-managed/dynamic).
	const effortPillLabel = validatedEffort
		? effortLabel(validatedEffort)
		: effortDefault
			? effortLabel(effortDefault)
			: "Auto";
	const vision =
		selectedModelData === undefined || selectedModelData.multimodal;
	useEffect(() => {
		if (vision || acceptsFiles !== false) return;
		const unsupported = controller.attachments.files.filter(
			(file) =>
				file.mediaType.startsWith("image/") &&
				file.mediaType !== "image/svg+xml",
		);
		for (const file of unsupported) {
			controller.attachments.remove(file.id);
		}
		if (unsupported.length > 0) {
			toast.error("Images are unavailable for this model and agent.");
		}
	}, [acceptsFiles, controller.attachments, vision]);
	const enabledDisconnectedServers = useMemo(() => {
		if (effectiveThreadToolMode === "no_tools") return [];
		if (
			effectiveThreadToolMode === "lazy" ||
			effectiveThreadToolMode === "force_all"
		) {
			return disconnectedServers;
		}
		const disabledIds = new Set(resourceSettings.disabledMcpServerIds);
		return disconnectedServers.filter((server) => !disabledIds.has(server.id));
	}, [
		disconnectedServers,
		effectiveThreadToolMode,
		resourceSettings.disabledMcpServerIds,
	]);
	const conversationStats = useMemo(() => {
		const messages = statsMessages ?? conversationMessages;
		if (!messages) return null;
		let userMessages = 0;
		let assistantMessages = 0;
		let modelCalls = 0;
		let toolCalls = 0;
		let inputTokens = 0;
		let outputTokens = 0;
		let totalTokens = 0;
		let cachedInputTokens = 0;
		let reasoningTokens = 0;
		let hasUsage = false;
		let hasToolResultSinceLastModelCall = false;
		const calls: {
			number: number;
			phase: "initial" | "follow-up" | "after-tools";
			inputTokens: number;
			outputTokens: number;
			totalTokens: number;
		}[] = [];

		for (const message of messages) {
			if (isHumanMessage(message) && message.name !== "host") {
				userMessages += 1;
				continue;
			}
			if (isToolMessage(message)) {
				hasToolResultSinceLastModelCall = true;
				continue;
			}
			if (!isAIMessage(message)) continue;
			modelCalls += 1;
			toolCalls += message.tool_calls?.length ?? 0;
			if (message.text.trim()) assistantMessages += 1;

			const usage = message.usage_metadata;
			if (!usage) {
				hasToolResultSinceLastModelCall = false;
				continue;
			}
			hasUsage = true;
			const input = usage.input_tokens ?? 0;
			const output = usage.output_tokens ?? 0;
			const total = usage.total_tokens ?? input + output;
			inputTokens += input;
			outputTokens += output;
			totalTokens += total;
			cachedInputTokens += usage.input_token_details?.cache_read ?? 0;
			reasoningTokens += usage.output_token_details?.reasoning ?? 0;
			calls.push({
				number: modelCalls,
				phase:
					calls.length === 0
						? "initial"
						: hasToolResultSinceLastModelCall
							? "after-tools"
							: "follow-up",
				inputTokens: input,
				outputTokens: output,
				totalTokens: total,
			});
			hasToolResultSinceLastModelCall = false;
		}

		const initialInputTokens = calls[0]?.inputTokens ?? 0;
		return {
			userMessages,
			assistantMessages,
			messageCount: userMessages + assistantMessages,
			modelCalls,
			toolCalls,
			inputTokens,
			outputTokens,
			totalTokens,
			cachedInputTokens,
			reasoningTokens,
			hasUsage,
			initialInputTokens,
			laterInputTokens: Math.max(0, inputTokens - initialInputTokens),
			afterToolInputTokens: calls
				.filter((call) => call.phase === "after-tools")
				.reduce((sum, call) => sum + call.inputTokens, 0),
			calls,
		};
	}, [conversationMessages, statsMessages]);

	const handleStatsDialogOpenChange = (open: boolean) => {
		setStatsDialogOpen(open);
		const request = ++statsRequestRef.current;
		if (!open || !loadLatestConversationMessages) return;

		setStatsLoading(true);
		void Promise.all([
			loadLatestConversationMessages(),
			new Promise<void>((resolve) => {
				window.setTimeout(resolve, STATS_LOADER_MIN_MS);
			}),
		])
			.then(([messages]) => {
				if (statsRequestRef.current === request) {
					setStatsMessages(messages);
				}
			})
			.catch((error: unknown) => {
				if (statsRequestRef.current === request) {
					toast.error(
						getApiErrorMessage(error, "Conversation stats could not be loaded."),
					);
				}
			})
			.finally(() => {
				if (statsRequestRef.current === request) {
					setStatsLoading(false);
				}
			});
	};

	// Editable composer only: normalize a stale selection in the parent state
	// too (not just the display), so what's shown as Default/Auto is also what
	// gets submitted. Read-only threads keep their pinned value — the backend
	// clamps it at run time. On a thread this persists the clamp; a failure
	// is silent since the server clamps the same way on its own.
	useEffect(() => {
		if (
			!readOnlyEffort &&
			selectedEffort &&
			selectedModelData !== undefined &&
			!selectedModelData.reasoningEffortLevels.includes(selectedEffort)
		) {
			void Promise.resolve(onEffortChange?.(null)).catch(() => undefined);
		}
	}, [readOnlyEffort, selectedEffort, selectedModelData, onEffortChange]);

	useEffect(() => {
		let cancelled = false;
		void agentsApi
			.getAgent(agentId)
			.then((agent) => {
				if (cancelled) return;
				setToolDiscoveryConfig({
					agentId,
					mode: agent.toolDiscoveryMode ?? "disabled",
				});
			})
			.catch(() => {
				// The composer remains usable if this optional control cannot load.
			});
		return () => {
			cancelled = true;
		};
	}, [agentId]);

	const handleToolModeChange = (mode: ThreadToolMode | null) => {
		if (mode === resourceSettings.toolMode || !canChangeToolMode) return;
		onResourceSettingsChange({ ...resourceSettings, toolMode: mode });
		const label =
			mode === null
				? "Agent default"
				: THREAD_TOOL_MODE_LABELS[mode];
		toast.success(`Tool mode set to ${label} for the next message.`);
	};

	const handleModelChange = async (modelId: string) => {
		if (configurationLocked) return;
		if (modelId === currentModel) {
			handleModelSelectorOpenChange(false);
			return;
		}
		setModelUpdatePending(true);
		try {
			await onModelChange?.(modelId);
			setModel(modelId);
			handleModelSelectorOpenChange(false);
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation model could not be changed."),
			);
		} finally {
			setModelUpdatePending(false);
		}
	};

	const handleEffortChange = async (effort: string | null) => {
		if (configurationLocked || effortUpdatePending) return;
		if (effort === validatedEffort) return;
		setEffortUpdatePending(true);
		try {
			await onEffortChange?.(effort);
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The reasoning effort could not be changed."),
			);
		} finally {
			setEffortUpdatePending(false);
		}
	};

	const groupedModels = useMemo(() => {
		const q = modelSearch.trim().toLowerCase();
		const filtered = q
			? models.filter(
					(m) =>
						m.name.toLowerCase().includes(q) ||
						m.chef.toLowerCase().includes(q),
				)
			: models;
		return filtered.reduce(
			(acc, model) => {
				acc[model.chef] = acc[model.chef] || [];
				acc[model.chef].push(model);
				return acc;
			},
			{} as Record<string, Model[]>,
		);
	}, [models, modelSearch]);

	const hasModelResults = Object.keys(groupedModels).length > 0;

	const handleModelSelectorOpenChange = (open: boolean) => {
		setModelSelectorOpen(open);
		if (!open) setModelSearch("");
	};

	useLayoutEffect(
		() => {
			mountedRef.current = true;
			return () => {
				mountedRef.current = false;
				if (draftRef.current !== null) {
					setThreadDraft(draftKey, draftRef.current);
					draftRef.current = null;
				}
			};
		},
		[draftKey, setThreadDraft],
	);

	useEffect(() => {
		if (!initialFocusPendingRef.current || queueLoading) {
			return;
		}

		const frame = requestAnimationFrame(() => {
			textareaRef.current?.focus({ preventScroll: true });
			initialFocusPendingRef.current = false;
		});
		return () => {
			cancelAnimationFrame(frame);
		};
	}, [queueLoading]);

	useEffect(() => {
		if (wasCompletedRef.current && !completed) {
			requestAnimationFrame(() => {
				textareaRef.current?.focus({ preventScroll: true });
			});
		}
		wasCompletedRef.current = completed;
	}, [completed]);

	const submitMessage = async (message: PromptInputMessage) => {
		const hasText = Boolean("text" in message && message.text);
		const hasAttachments = Boolean("files" in message && message.files?.length);

		if (effectiveEditingId) {
			if (!hasText || hasAttachments || !onUpdateQueued) return;
			const submittedDraft = controller.textInput.draftIdentity();
			const draft = draftRef.current;
			setBusyId(effectiveEditingId);
			try {
				await onUpdateQueued(effectiveEditingId, message.text?.trim() ?? "");
				setEditingId(null);
				draftRef.current = null;
				const currentDraft = controller.textInput.draftIdentity();
				if (
					mountedRef.current &&
					activeDraftKeyRef.current === draftKey &&
					currentDraft.key === submittedDraft.key &&
					currentDraft.revision === submittedDraft.revision
				) {
					setThreadDraft(draftKey, draft ?? "");
				}
			} catch (error) {
				toast.error(
					getApiErrorMessage(
						error,
						"The queued prompt could not be updated.",
					),
				);
				throw error;
			} finally {
				setBusyId(null);
			}
			return;
		}
		const enqueue = async () => {
			if (!(hasText || hasAttachments) || !onEnqueue) return;
			try {
				await onEnqueue(message);
			} catch (error) {
				if (error instanceof DOMException && error.name === "AbortError") {
					throw error;
				}
				const apiError = toApiError(error);
				if (apiError.status === 401) {
					onQueueAuthorizationRequired?.();
					const body =
						apiError.body && typeof apiError.body === "object"
							? (apiError.body as Record<string, unknown>)
							: null;
					const authUrl = safeHttpUrl(body?.auth_url);
					if (authUrl) {
						const redirectMode =
							body?.oauth_redirect_mode === "loopback_manual"
								? "loopback_manual"
								: "hosted_callback";
						toast.error(
							"Reconnect the agent's MCP server before queueing this prompt.",
							{
								action: {
									label: "Connect",
									onClick: () => {
										startAuthorization({
											authUrl,
											redirectMode,
										});
									},
								},
							},
						);
						throw error;
					}
					setConnectDialogOpen(true);
				}
				toast.error(
					getApiErrorMessage(
						error,
						"The prompt could not be added to the queue.",
					),
				);
				throw error;
			}
		};
		if (queueMode || directRunLockRef.current) {
			await enqueue();
			return;
		}
		directRunLockRef.current = true;
		try {
			await onSubmit(message);
		} catch (error) {
			if (error instanceof DOMException && error.name === "AbortError") {
				throw error;
			}
			// The session refused a second direct send while a run is still
			// active (the `queueMode` prop lagged behind): queue it instead.
			if (
				error instanceof DOMException &&
				error.name === "InvalidStateError" &&
				onEnqueue
			) {
				await enqueue();
				return;
			}
			toast.error(getApiErrorMessage(error, "The message could not be sent."));
			throw error;
		} finally {
			// `onSubmit` settles once the server has accepted the run (or
			// refused it), by which point `queueMode` reflects the active run,
			// so the lock can be released here as well as on the `status`
			// transition.
			directRunLockRef.current = false;
		}
	};

	const handleSubmit = (message: PromptInputMessage) => {
		if (
			!message ||
			queueLoading ||
			submissionDisabled ||
			completed ||
			modelUpdatePending ||
			preparingSubmission
		) {
			return;
		}
		const hasText = Boolean("text" in message && message.text);
		const hasAttachments = Boolean("files" in message && message.files?.length);
		if (!(hasText || hasAttachments)) return;
		if (hasAttachments && acceptsFiles === null) {
			toast.error("File support is still being checked. Try again in a moment.");
			throw new Error("File support is still being checked");
		}

		const submission = submitMessage(message);
		setPreparingSubmission(true);
		requestAnimationFrame(() => {
			textareaRef.current?.focus({ preventScroll: true });
		});
		return submission.finally(() => {
			setPreparingSubmission(false);
		});
	};

	useEffect(() => {
		if (status === "ready") {
			directRunLockRef.current = false;
		}
	}, [status]);

	const finishEditingLocally = () => {
		setEditingId(null);
		if (draftRef.current !== null) {
			setThreadDraft(draftKey, draftRef.current);
			draftRef.current = null;
		}
	};

	const beginEdit = (item: QueuedPrompt) => {
		if (controller.attachments.files.length > 0) {
			toast.error("Send or remove the current attachments before editing.");
			return;
		}
		setBusyId(item.id);
		void (async () => {
			try {
				await onBeginQueuedEdit?.(item.id);
				if (
					!mountedRef.current ||
					activeDraftKeyRef.current !== draftKey
				) {
					if (onEndQueuedEdit) {
						await onEndQueuedEdit(item.id).catch(() => {});
					}
					return;
				}
				if (editingId === null) {
					draftRef.current = controller.textInput.draftValue(draftKey);
				}
				setThreadDraft(draftKey, item.text);
				setEditingId(item.id);
				requestAnimationFrame(() => {
					textareaRef.current?.focus();
				});
			} catch (error) {
				toast.error(
					getApiErrorMessage(error, "This queued prompt can no longer be edited."),
				);
			} finally {
				setBusyId(null);
			}
		})();
	};

	const cancelEdit = () => {
		if (!effectiveEditingId) return;
		const id = effectiveEditingId;
		setBusyId(id);
		void (async () => {
			try {
				await onEndQueuedEdit?.(id);
				finishEditingLocally();
			} catch (error) {
				toast.error(
					getApiErrorMessage(error, "The queued prompt edit could not be closed."),
				);
			} finally {
				setBusyId(null);
			}
		})();
	};

	useEffect(() => {
		if (!effectiveEditingId || !onBeginQueuedEdit) return;
		const timer = window.setInterval(() => {
			void onBeginQueuedEdit(effectiveEditingId).catch(() => {});
		}, 10_000);
		return () => {
			window.clearInterval(timer);
		};
	}, [effectiveEditingId, onBeginQueuedEdit]);

	useEffect(() => {
		if (
			editingId === null ||
			queuedPrompts.some((item) => item.id === editingId)
		) {
			return;
		}
		// The queue is an external server subscription; losing its item ends
		// the local editing session.
		const timeoutId = window.setTimeout(() => {
			setEditingId(null);
			setThreadDraft(draftKey, draftRef.current ?? "");
			draftRef.current = null;
			toast.info("That prompt has started, so it can no longer be edited.");
		}, 0);
		return () => {
			window.clearTimeout(timeoutId);
		};
	}, [draftKey, editingId, queuedPrompts, setThreadDraft]);

	const removeQueued = async (id: string) => {
		setBusyId(id);
		try {
			await onRemoveQueued?.(id);
			if (editingId === id) finishEditingLocally();
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The queued prompt could not be removed."),
			);
		} finally {
			setBusyId(null);
		}
	};

	const sendQueuedNow = async (id: string) => {
		setBusyId(id);
		try {
			await onSendQueuedNow?.(id);
			if (editingId === id) finishEditingLocally();
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The queued prompt could not be sent now."),
			);
		} finally {
			setBusyId(null);
		}
	};

	const reorderQueued = async (orderedIds: string[]) => {
		try {
			await onReorderQueued?.(orderedIds);
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The prompt queue could not be reordered."),
			);
		}
	};

	useEffect(() => {
		// Only fetch if we don't have models yet
		if (models.length === 0) {
			fetchModels();
		}
	}, [fetchModels, models.length]);

	return (
		<>
			<div className={className}>
				<PromptQueue
					items={queuedPrompts}
					editingId={effectiveEditingId}
					busyId={busyId}
					onEdit={beginEdit}
					onSendNow={sendQueuedNow}
					sendNowDisabled={sendQueuedNowDisabled}
					onRemove={removeQueued}
					onReorder={reorderQueued}
				/>
				{effectiveEditingId && (
					<div className="mb-2 flex items-center gap-2 rounded-lg border border-sky-400/35 bg-sky-500/[0.07] px-3 py-2 text-[12px] font-medium text-sky-700 dark:text-sky-300">
						<span className="size-1.5 rounded-full bg-sky-500" />
						Editing queued prompt
						<span className="flex-1 text-sky-700/65 dark:text-sky-300/65">
							Submit to save
						</span>
						<button
							type="button"
							onClick={cancelEdit}
							className="flex size-6 cursor-pointer items-center justify-center rounded-md transition-colors hover:bg-sky-500/10"
							aria-label="Cancel queued prompt editing"
						>
							<XIcon className="size-3.5" />
						</button>
					</div>
				)}
				<div className="relative">
				<PromptInput
					globalDrop
					multiple
					maxFiles={10}
					disableAttachments={effectiveEditingId !== null || completed}
					inert={completed ? true : undefined}
					attachmentsDisabledMessage={
						effectiveEditingId
							? "Attachments cannot be changed while editing a queued prompt"
							: undefined
					}
					onError={(error) => {
						toast.error(error.message);
					}}
					onSubmit={handleSubmit}
					className={cn(
					"min-h-[116px] transition-all duration-200",
					// Petrol Mono composer (design kit 09): 16px radius, 2px #DCE4E4
					// border → petrol on focus, depth from the composer shadow.
					"[&>[data-slot=input-group]]:rounded-2xl",
					"[&>[data-slot=input-group]]:border-2",
					"[&>[data-slot=input-group]]:border-input",
					"[&>[data-slot=input-group]]:bg-card",
					"[&>[data-slot=input-group]]:shadow-composer",
					"[&>[data-slot=input-group]]:transition-colors",
					effectiveEditingId
						? "[&>[data-slot=input-group]]:border-sky-400/65 [&>[data-slot=input-group]:focus-within]:border-sky-500"
						: "[&>[data-slot=input-group]:focus-within]:border-petrol",
					// Remove default focus ring
					"[&>[data-slot=input-group]]:has-[[data-slot=input-group-control]:focus-visible]:ring-0",
				)}
				>
				<PromptInputAttachments className="w-full justify-start px-[18px] pt-4">
					{(attachment) => <PromptInputAttachment data={attachment} />}
				</PromptInputAttachments>
				<PromptInputBody>
					<PromptInputTextarea
						ref={textareaRef}
						disabled={queueLoading || completed}
						onKeyDown={(event) => {
							// Escape leaves edit mode without saving: the lease is
							// released and the pre-edit draft comes back.
							if (event.key !== "Escape" || !effectiveEditingId) return;
							event.preventDefault();
							cancelEdit();
						}}
						placeholder={agentName ? `Reply to ${agentName}…` : "Ask anything…"}
						className={cn(
							"text-[15px] font-medium leading-relaxed",
							"text-foreground",
							"placeholder:text-meta dark:placeholder:text-panel-dim",
							"px-[18px] pt-4 pb-2",
						)}
					/>
				</PromptInputBody>
				<PromptInputFooter className="items-end gap-x-2 gap-y-1.5 px-3 pt-0 pb-3">
					<PromptInputTools className="min-w-0 flex-1 flex-wrap items-center gap-1.5">
						<PromptInputAddAttachmentButton
							disabled={effectiveEditingId !== null}
							className={cn(
								composerPillClass,
								"w-[34px] px-0 text-subtle dark:text-panel-body",
							)}
						/>
						{conversationStats && (
							<Dialog
								open={statsDialogOpen}
								onOpenChange={handleStatsDialogOpenChange}
							>
								<DialogTrigger asChild>
									<PromptInputButton
										aria-label="Conversation stats"
										title="Conversation stats"
										className={cn(
											composerPillClass,
											"w-[34px] cursor-pointer px-0 text-subtle dark:text-panel-body",
										)}
									>
										<ChartNoAxesColumnIncreasingIcon className="size-3.5" />
									</PromptInputButton>
								</DialogTrigger>
								<DialogContent className="max-h-[85vh] gap-0 overflow-y-auto sm:max-w-[600px]">
									<DialogTitle>Conversation stats</DialogTitle>
									<DialogDescription className="mt-1.5">
										Provider-reported usage from model responses stored in
										this thread. Internal routing calls are not included.
									</DialogDescription>

									{statsLoading ? (
										<div
											className="flex min-h-48 items-center justify-center gap-2 text-[13px] text-meta dark:text-panel-dim"
											aria-live="polite"
										>
											<Loader2 className="size-4 animate-spin" />
											Loading latest stats…
										</div>
									) : (
										<>
											<div className="mt-5 grid grid-cols-3 gap-2.5">
										<ConversationStat
											label="Total tokens"
											value={
												conversationStats.hasUsage
													? conversationStats.totalTokens
													: null
											}
											primary
										/>
										<ConversationStat
											label="Input tokens"
											value={
												conversationStats.hasUsage
													? conversationStats.inputTokens
													: null
											}
										/>
										<ConversationStat
											label="Output tokens"
											value={
												conversationStats.hasUsage
													? conversationStats.outputTokens
													: null
											}
										/>
									</div>

									{conversationStats.hasUsage && (
										<>
											<div className="mt-5">
												<h3 className="text-[12px] font-semibold text-foreground">
													Context loading
												</h3>
												<p className="mt-1 text-[11.5px] leading-[1.5] text-meta dark:text-panel-dim">
													Initial input is the first model request. Later input
													is the sum of every subsequent request, including
													context sent again.
												</p>
											</div>
											<div className="mt-3 grid grid-cols-3 gap-2.5">
												<ConversationStat
													label="Initial input"
													value={conversationStats.initialInputTokens}
												/>
												<ConversationStat
													label="Later input"
													value={conversationStats.laterInputTokens}
												/>
												<ConversationStat
													label="Input after tools"
													value={conversationStats.afterToolInputTokens}
												/>
											</div>

											<div className="mt-4 rounded-[8px] bg-hover px-3 py-2.5 text-[11.5px] leading-[1.55] text-meta dark:bg-white/5 dark:text-panel-dim">
												<span className="font-semibold text-body dark:text-panel-body">
													How tools are counted:
												</span>{" "}
												tool schemas are part of model input, tool-call arguments
												are model output, and tool results become model input on a
												later call. Tool execution itself does not use model
												tokens. Providers do not report an exact token breakdown
												by source.
											</div>

											<div className="mt-5">
												<h3 className="text-[12px] font-semibold text-foreground">
													Model input by call
												</h3>
												<p className="mt-1 text-[11.5px] leading-[1.5] text-meta dark:text-panel-dim">
													Each row is the full context sent for that call, not
													only the new tokens added since the previous call.
												</p>
											</div>
											<div className="mt-3 max-h-52 overflow-y-auto rounded-[10px] border border-border">
												{conversationStats.calls.map((call, index) => (
													<ConversationTokenCallRow
														key={call.number}
														call={call}
														last={index === conversationStats.calls.length - 1}
													/>
												))}
											</div>
										</>
									)}

									<div className="mt-5 overflow-hidden rounded-[10px] border border-border">
										<ConversationStatRow
											label="Messages"
											value={conversationStats.messageCount}
										/>
										<ConversationStatRow
											label="Your messages"
											value={conversationStats.userMessages}
										/>
										<ConversationStatRow
											label="Assistant messages"
											value={conversationStats.assistantMessages}
										/>
										<ConversationStatRow
											label="Model calls"
											value={conversationStats.modelCalls}
										/>
										<ConversationStatRow
											label="Tool calls"
											value={conversationStats.toolCalls}
											last={
												conversationStats.cachedInputTokens === 0 &&
												conversationStats.reasoningTokens === 0
											}
										/>
										{conversationStats.cachedInputTokens > 0 && (
											<ConversationStatRow
												label="Cached input tokens"
												value={conversationStats.cachedInputTokens}
												last={conversationStats.reasoningTokens === 0}
											/>
										)}
										{conversationStats.reasoningTokens > 0 && (
											<ConversationStatRow
												label="Reasoning tokens"
												value={conversationStats.reasoningTokens}
												last
											/>
										)}
									</div>

											{!conversationStats.hasUsage && (
												<p className="mt-4 rounded-[8px] bg-hover px-3 py-2.5 text-[12px] leading-[1.5] text-meta dark:bg-white/5 dark:text-panel-dim">
													Token usage is not available for the responses in this
													conversation.
												</p>
											)}
										</>
									)}
								</DialogContent>
							</Dialog>
						)}
						<ConnectButton
							needsConnection={
								agentReady === false &&
								enabledDisconnectedServers.length > 0
							}
							onClick={() => {
								setConnectDialogOpen(true);
							}}
						/>
						{readOnlyModel ? (
							<PromptInputButton
								disabled
								className={cn(composerPillClass, "min-w-0 max-w-52")}
							>
								{selectedModelData?.chefSlug && (
									<ModelSelectorLogo provider={selectedModelData.chefSlug} />
								)}
								{selectedModelData?.name && (
									<span className="truncate text-left">
										{selectedModelData.name}
									</span>
								)}
							</PromptInputButton>
						) : (
							<Dialog
								open={modelSelectorOpen}
								onOpenChange={handleModelSelectorOpenChange}
							>
								<DialogTrigger asChild>
									<PromptInputButton
										disabled={modelUpdatePending || configurationLocked}
										className={cn(
											composerPillClass,
											"min-w-0 max-w-52 cursor-pointer",
										)}
									>
										{selectedModelData ? (
											<>
												<ModelSelectorLogo
													provider={selectedModelData.chefSlug}
												/>
												<span className="truncate text-left">
													{selectedModelData.name}
												</span>
											</>
										) : (
											<span className="truncate text-left text-meta dark:text-panel-dim">
												Select model
											</span>
										)}
									</PromptInputButton>
								</DialogTrigger>
								<DialogContent
									className="max-h-[calc(100dvh-2rem)] gap-0 overflow-hidden! p-0 sm:max-w-[400px]"
									onKeyDown={handleKeyboardListNavigation}
								>
									<div className="px-5 pt-5 pb-4 sm:px-6 sm:pt-6">
										<DialogTitle>Select a model</DialogTitle>
										<DialogDescription className="mt-1.5">
											Choose the model powering this chat
										</DialogDescription>
									</div>

									<div className="px-5 pb-3 sm:px-6">
										<SearchBar
											placeholder="Search models..."
											value={modelSearch}
											onChange={setModelSearch}
										/>
									</div>

									<div
										role="listbox"
										className="max-h-[min(55vh,420px)] overflow-auto px-3 pb-4 [scrollbar-width:none] sm:px-4 sm:pb-5 [&::-webkit-scrollbar]:hidden"
									>
										{!hasModelResults ? (
											<div className="px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
												No models found.
											</div>
										) : (
											Object.entries(groupedModels).map(
												([chefName, chefModels]) => (
													<div key={chefName} className="px-2 pt-2">
														<div className="px-3 pb-1.5 text-[10px] font-semibold text-meta dark:text-panel-dim">
															{chefName}
														</div>
														<div className="flex flex-col gap-0.5">
															{chefModels.map((m) => {
																const isActive = currentModel === m.id;
																return (
																	<button
																		key={m.id}
																		type="button"
																		role="option"
																		data-keyboard-option="true"
																		aria-selected={isActive}
																		disabled={
																			modelUpdatePending || configurationLocked
																		}
																		onClick={() => {
																			void handleModelChange(m.id);
																		}}
																		className={cn(
																			"flex w-full items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-colors text-left outline-none focus-visible:bg-hover focus-visible:ring-2 focus-visible:ring-petrol/35 dark:focus-visible:bg-white/5",
																			"text-[13.5px] font-medium text-foreground",
																			isActive
																				? "bg-petrol-tint dark:bg-white/10"
																				: "hover:bg-hover dark:hover:bg-white/5",
																		)}
																	>
																		<ModelSelectorLogo provider={m.chefSlug} />
																		<span className="flex-1 truncate">
																			{m.name}
																		</span>
																		{isActive && (
																			<CheckIcon
																				className="ml-auto size-4 shrink-0 text-petrol"
																				strokeWidth={3}
																			/>
																		)}
																	</button>
																);
															})}
														</div>
													</div>
												),
											)
										)}
									</div>
								</DialogContent>
							</Dialog>
						)}
						{readOnlyEffort
							? // Show a stored explicit effort while keeping it immutable.
								validatedEffort && (
									<PromptInputButton disabled className={composerPillClass}>
										<BrainIcon className="size-3.5" />
										<span className="truncate text-left">
											{effortLabel(validatedEffort)}
										</span>
									</PromptInputButton>
								)
							: effortLevels.length > 0 && (
									<DropdownMenu
										align="start"
										side="top"
										className={composerMenuClass}
										items={[
											{ sectionLabel: "Reasoning effort" },
											{
												label: effortDefault
													? `Default (${effortLabel(effortDefault)})`
													: "Auto",
												active: !validatedEffort,
												onClick: () => {
													void handleEffortChange(null);
												},
											},
											...effortLevels.map((level) => ({
												label: effortLabel(level),
												active: validatedEffort === level,
												onClick: () => {
													void handleEffortChange(level);
												},
											})),
										]}
										trigger={
											<PromptInputButton
												disabled={configurationLocked || effortUpdatePending}
												className={cn(composerPillClass, "cursor-pointer")}
											>
												<BrainIcon className="size-3.5" />
												<span className="truncate text-left">
													{effortPillLabel}
												</span>
											</PromptInputButton>
										}
									/>
								)}
						{effectiveThreadToolMode && (
							<DropdownMenu
								align="start"
								side="top"
								className={cn(composerMenuClass, "w-[430px]")}
								itemClassName="py-[9px]"
								items={[
									{ sectionLabel: "Tool mode" },
									{
										label: agentDefaultThreadToolMode
											? `Agent default (${THREAD_TOOL_MODE_LABELS[agentDefaultThreadToolMode]})`
											: "Agent default",
										description: "follow agent configuration",
										active: resourceSettings.toolMode === null,
										onClick: () => {
											handleToolModeChange(null);
										},
									},
									{ separator: true },
									{ sectionLabel: "Uses resource selections" },
									{
										label: "Eager",
										description: "load every tool from enabled MCP servers",
										active: resourceSettings.toolMode === "eager",
										onClick: () => {
											handleToolModeChange("eager");
										},
									},
									{
										label: "Precision",
										description: "find relevant tools from enabled MCP servers",
										active: resourceSettings.toolMode === "precision",
										onClick: () => {
											handleToolModeChange("precision");
										},
									},
									{ separator: true },
									{ sectionLabel: "Overrides resource selections" },
									{
										label: "No tools",
										description: "disable every conversation resource",
										active: resourceSettings.toolMode === "no_tools",
										onClick: () => {
											handleToolModeChange("no_tools");
										},
									},
									{
										label: "Lazy",
										description: "enable all resources; choose MCPs per prompt",
										active: resourceSettings.toolMode === "lazy",
										onClick: () => {
											handleToolModeChange("lazy");
										},
									},
									{
										label: "Force all",
										description: "enable all resources; load every MCP tool",
										active: resourceSettings.toolMode === "force_all",
										onClick: () => {
											handleToolModeChange("force_all");
										},
									},
								]}
								trigger={
									<PromptInputButton
										disabled={
											resourceSettingsSaving || !canChangeToolMode
										}
										aria-label={`Tool mode: ${THREAD_TOOL_MODE_LABELS[effectiveThreadToolMode]}`}
										title={
											canChangeToolMode
												? `Tool mode: ${THREAD_TOOL_MODE_LABELS[effectiveThreadToolMode]}${
														resourceSettings.toolMode === null
															? " (agent default)"
															: ""
													}`
												: readOnlyModel
													? "This conversation is read-only"
													: "Wait for the current run to finish"
										}
										className={cn(composerPillClass, "cursor-pointer")}
									>
										{resourceSettingsSaving ? (
											<Loader2 className="size-3.5 animate-spin" />
										) : (
											<CpuIcon className="size-3.5" />
										)}
										<span className="truncate text-left">
											{THREAD_TOOL_MODE_LABELS[effectiveThreadToolMode]}
										</span>
									</PromptInputButton>
								}
							/>
						)}
					</PromptInputTools>
					<div className="flex shrink-0 items-center gap-1.5">
						{status === "streaming" && stop && (
							<StopButton stop={stop} stopping={stopping} />
						)}
						<SubmitButton
							disabled={
								queueLoading ||
								submissionDisabled ||
								completed ||
								modelUpdatePending ||
								preparingSubmission
							}
						/>
					</div>
				</PromptInputFooter>
				</PromptInput>
				{completed && (
					<div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-card/72 backdrop-blur-[1px]">
						<button
							type="button"
							disabled={reopening}
							onClick={() => {
								onReopen?.();
							}}
							className="flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-full bg-petrol px-4 py-2 text-[13px] font-semibold text-white shadow-submit transition-opacity hover:opacity-90 disabled:cursor-wait disabled:opacity-60"
						>
							{reopening && <Loader2 className="size-3.5 animate-spin" />}
							{reopening ? "Reopening…" : "Reopen conversation"}
						</button>
					</div>
				)}
				</div>
			</div>
			<ConnectServersDialog
				open={connectDialogOpen}
				onOpenChange={setConnectDialogOpen}
				agentId={agentId}
				disconnectedServers={disconnectedServers}
				onConnectionChange={() => onAllConnected?.()}
				toolMode={effectiveThreadToolMode}
				resourceSettings={resourceSettings}
				onResourceSettingsChange={onResourceSettingsChange}
				resourceSettingsSaving={
					resourceSettingsSaving || preparingSubmission
				}
			/>
		</>
	);
};

const formatStat = (value: number | null) =>
	value === null ? "N/A" : new Intl.NumberFormat("en-US").format(value);

const ConversationStat = ({
	label,
	value,
	primary = false,
}: {
	label: string;
	value: number | null;
	primary?: boolean;
}) => (
	<div
		className={cn(
			"rounded-[10px] border px-3 py-3",
			primary
				? "border-petrol/20 bg-petrol-tint dark:border-white/10 dark:bg-white/10"
				: "border-border bg-card",
		)}
	>
		<div
			className={cn(
				"font-mono text-[18px] font-semibold tracking-[-0.03em]",
				primary ? "text-petrol dark:text-panel-terminal" : "text-foreground",
			)}
		>
			{formatStat(value)}
		</div>
		<div className="mt-1 text-[10.5px] font-medium leading-tight text-meta dark:text-panel-dim">
			{label}
		</div>
	</div>
);

const ConversationStatRow = ({
	label,
	value,
	last = false,
}: {
	label: string;
	value: number;
	last?: boolean;
}) => (
	<div
		className={cn(
			"flex items-center justify-between px-3.5 py-2.5",
			!last && "border-b border-hairline dark:border-white/5",
		)}
	>
		<span className="text-[12.5px] font-medium text-body dark:text-panel-body">
			{label}
		</span>
		<span className="font-mono text-[12px] font-semibold text-foreground">
			{formatStat(value)}
		</span>
	</div>
);

const ConversationTokenCallRow = ({
	call,
	last = false,
}: {
	call: {
		number: number;
		phase: "initial" | "follow-up" | "after-tools";
		inputTokens: number;
		outputTokens: number;
		totalTokens: number;
	};
	last?: boolean;
}) => {
	const phaseLabel = {
		initial: "Initial load",
		"follow-up": "Follow-up",
		"after-tools": "After tool results",
	}[call.phase];

	return (
		<div
			className={cn(
				"flex items-center justify-between gap-4 px-3.5 py-2.5",
				!last && "border-b border-hairline dark:border-white/5",
			)}
		>
			<div className="min-w-0">
				<div className="text-[12.5px] font-medium text-body dark:text-panel-body">
					Call {call.number}
				</div>
				<div className="mt-0.5 text-[10.5px] text-meta dark:text-panel-dim">
					{phaseLabel}
				</div>
			</div>
			<div className="shrink-0 text-right">
				<div className="font-mono text-[12px] font-semibold text-foreground">
					{formatStat(call.inputTokens)} in
				</div>
				<div className="mt-0.5 font-mono text-[10.5px] text-meta dark:text-panel-dim">
					{formatStat(call.outputTokens)} out / {formatStat(call.totalTokens)} total
				</div>
			</div>
		</div>
	);
};

const SubmitButton = ({ disabled = false }: { disabled?: boolean }) => {
	const controller = usePromptInputController();
	const input = controller.textInput.value;
	const hasContent =
		Boolean(input.trim()) || controller.attachments.files.length > 0;
	const isDisabled = disabled || !hasContent;

	return (
		<button
			type="submit"
			disabled={isDisabled}
			className={cn(
				"flex size-[38px] items-center justify-center rounded-full transition-all",
				isDisabled
					? "cursor-not-allowed bg-hover text-ghost dark:bg-white/5 dark:text-panel-dim"
					: "cursor-pointer bg-petrol text-white shadow-submit hover:opacity-90",
			)}
		>
			<svg
				width="20"
				height="20"
				viewBox="0 0 20 20"
				fill="currentColor"
				xmlns="http://www.w3.org/2000/svg"
			>
				<path d="M8.99992 16V6.41407L5.70696 9.70704C5.31643 10.0976 4.68342 10.0976 4.29289 9.70704C3.90237 9.31652 3.90237 8.6835 4.29289 8.29298L9.29289 3.29298L9.36907 3.22462C9.76184 2.90427 10.3408 2.92686 10.707 3.29298L15.707 8.29298L15.7753 8.36915C16.0957 8.76192 16.0731 9.34092 15.707 9.70704C15.3408 10.0732 14.7618 10.0958 14.3691 9.7754L14.2929 9.70704L10.9999 6.41407V16C10.9999 16.5523 10.5522 17 9.99992 17C9.44764 17 8.99992 16.5523 8.99992 16Z" />
			</svg>
		</button>
	);
};

const StopButton = ({
	stop,
	stopping,
}: {
	stop: () => void;
	stopping: boolean;
}) => (
	<button
		type="button"
		disabled={stopping}
		onClick={stop}
		aria-label={stopping ? "Stopping current response" : "Stop current response"}
		className="flex size-[38px] cursor-pointer items-center justify-center rounded-full border border-input bg-card text-subtle transition-colors hover:border-destructive/35 hover:bg-destructive/8 hover:text-destructive disabled:cursor-wait disabled:border-input disabled:bg-card disabled:text-subtle"
	>
		{stopping ? (
			<Loader2 className="size-[18px] animate-spin" />
		) : (
			<svg width="18" height="18" viewBox="0 0 20 20" fill="currentColor">
				<rect x="5" y="5" width="10" height="10" rx="2" />
			</svg>
		)}
	</button>
);

const ConnectButton = ({
	needsConnection,
	onClick,
}: {
	needsConnection: boolean;
	onClick: () => void;
}) => {
	return (
		<button
			type="button"
			onClick={onClick}
			aria-label={
				needsConnection ? "Connect agent resources" : "View connected resources"
			}
			title={needsConnection ? undefined : "View agent resources"}
			className={cn(
				composerPillClass,
				"flex shrink-0 cursor-pointer items-center justify-center whitespace-nowrap",
				needsConnection
					? "bg-petrol text-white shadow-submit hover:bg-petrol hover:opacity-90 dark:bg-petrol dark:hover:bg-petrol"
					: "w-[34px] px-0 text-subtle dark:text-panel-body",
			)}
		>
			<PlugIcon className="size-3.5" />
			{needsConnection && <span>Connect</span>}
		</button>
	);
};

export default ChatPromptInput;

"use client";

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import {
	MessageActions,
	MessageAction,
	Message,
	MessageContent,
	MessageResponse,
} from "@/components/ai-elements/message";
import {
	Reasoning,
	ReasoningTrigger,
	ReasoningContent,
} from "@/components/ai-elements/reasoning";
import {
	Tool,
	ToolContent,
	ToolContentInner,
	ToolFooter,
	ToolHeader,
	ToolInput,
	ToolOutput,
} from "@/components/ai-elements/tool";
import type { AttachmentData } from "@/components/ai-elements/attachments";
import {
	Conversation,
	ConversationContent,
	ConversationScrollButton,
} from "@/components/ai-elements/conversation";
import {
	Error,
	ErrorContent,
	ErrorDetails,
} from "@/components/ai-elements/error";
import {
	Attachment,
	AttachmentPreview,
	AttachmentHoverCard,
	AttachmentHoverCardTrigger,
	AttachmentInfo,
	AttachmentHoverCardContent,
	getMediaCategory,
	getAttachmentLabel,
	Attachments,
} from "@/components/ai-elements/attachments";
import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import ChatPromptInput from "../components/prompt-input";
import { RefreshCcwIcon, CopyIcon, ArchiveIcon } from "lucide-react";
import {
	useStream,
	FetchStreamTransport,
} from "@langchain/langgraph-sdk/react";
import type { SubagentApi } from "@langchain/langgraph-sdk/ui";
import {
	SubAgentCard,
	SubAgentProgress,
	SynthesisIndicator,
} from "@/components/ai-elements/subagent";
import { TodoList } from "@/components/ai-elements/todo-list";
import type { Todo } from "@/components/ai-elements/todo-list";
import { useParams } from "next/navigation";
import { api, API_BASE_URL } from "@/lib/api/client";
import { ThinkingLoader, DotsLoader } from "../components/loader";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import { useHitlApprovals } from "@/hooks/use-hitl-approvals";
import { REATTACH_RUN_ID_KEY, useRunCancel } from "@/hooks/use-run-cancel";
import { useThrottledValue } from "@/hooks/use-throttled-value";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import {
	McpAppWidget,
	type McpAppToolInfo,
} from "../components/mcp-app-widget";

// ---------------------------------------------------------------------------
// Helpers for extracting content from LangChain messages
// ---------------------------------------------------------------------------

type LCToolCallEntry = {
	name: string;
	args: Record<string, unknown>;
	id?: string;
};

type LCMessage = {
	type: string;
	content: string | Array<Record<string, unknown>>;
	id?: string;
	name?: string;
	// snake_case (from stream / raw API)
	tool_calls?: LCToolCallEntry[];
	tool_call_id?: string;
	// camelCase (after Axios interceptor)
	toolCalls?: LCToolCallEntry[];
	toolCallId?: string;
	status?: string;
	additional_kwargs?: Record<string, unknown>;
	response_metadata?: Record<string, unknown>;
	artifact?: Record<string, unknown>;
	[key: string]: unknown;
};

function getTextContent(message: LCMessage): string {
	if (typeof message.content === "string") return message.content;
	if (Array.isArray(message.content)) {
		return message.content
			.filter((c) => c.type === "text")
			.map((c) => c.text as string)
			.join("");
	}
	return "";
}

function getReasoningContent(message: LCMessage): string | null {
	if (!Array.isArray(message.content)) return null;
	const thinking = message.content.filter((c) => c.type === "thinking");
	if (thinking.length === 0) return null;
	return thinking.map((c) => (c.thinking as string) || "").join("\n");
}

function getFileAttachments(message: LCMessage): AttachmentData[] {
	if (!Array.isArray(message.content)) return [];
	const attachments: AttachmentData[] = [];
	let idx = 0;

	for (const block of message.content) {
		// Image blocks: "image_url" (snake_case from stream) or "imageUrl" (camelCase from Axios)
		if (block.type === "image_url" || block.type === "imageUrl") {
			const imgField = block.image_url ?? block.imageUrl;
			const url =
				typeof imgField === "string"
					? imgField
					: (imgField as Record<string, string>)?.url || "";
			const dataUrl = url.startsWith("data:")
				? url
				: `data:image/jpeg;base64,${url}`;
			attachments.push({
				id: `${message.id}-file-${idx++}`,
				url: dataUrl,
				type: "file" as const,
				filename: "Image.jpg",
				mediaType: "image/jpeg",
			});
		}

		// File blocks: {"type": "file", "mime_type"/"mimeType": "...", "base64": "...", "filename": "..."}
		if (block.type === "file") {
			const mimeType = (block.mime_type ?? block.mimeType ?? "application/octet-stream") as string;
			const base64 = (block.base64 ?? "") as string;
			const filename = (block.filename ?? "file") as string;
			const dataUrl = `data:${mimeType};base64,${base64}`;
			attachments.push({
				id: `${message.id}-file-${idx++}`,
				url: dataUrl,
				type: "file" as const,
				filename,
				mediaType: mimeType,
			});
		}
	}

	return attachments;
}

// ---------------------------------------------------------------------------
// Tool name parsing (reused from old code)
// ---------------------------------------------------------------------------

const sanitizeToolIdentifier = (value: string): string => {
	const sanitized = value
		.replace(/[^a-zA-Z0-9_-]/g, "_")
		.replace(/^_+|_+$/g, "");
	return sanitized || "tool";
};

const getToolMetadata = (toolName: string, knownServerNames: string[]) => {
	for (const serverName of knownServerNames) {
		const aliases = [serverName, sanitizeToolIdentifier(serverName)];
		for (const alias of aliases) {
			if (toolName === alias || toolName.startsWith(`${alias}_`)) {
				const suffix = toolName.slice(alias.length);
				const name = suffix.startsWith("_") ? suffix.slice(1) : suffix;
				return { serverName, toolName: name || toolName };
			}
		}
	}
	const separatorIndex = toolName.indexOf("_");
	if (separatorIndex === -1) {
		return { serverName: toolName, toolName };
	}
	return {
		serverName: toolName.slice(0, separatorIndex),
		toolName: toolName.slice(separatorIndex + 1),
	};
};

// ---------------------------------------------------------------------------
// Compute tool calls from plain message dicts (for persisted history)
// ---------------------------------------------------------------------------

type LocalToolCall = {
	id: string;
	call: { name: string; args: Record<string, unknown>; id?: string };
	result: LCMessage | undefined;
	aiMessage: LCMessage;
	index: number;
	state: "pending" | "completed" | "error";
};

function computeToolCallsFromMessages(messages: LCMessage[]): LocalToolCall[] {
	// Axios camelCase interceptor converts snake_case keys from the API:
	//   tool_call_id → toolCallId, tool_calls → toolCalls
	// Handle both formats for robustness.
	const getToolCallId = (msg: LCMessage): string | undefined =>
		(msg.tool_call_id ?? msg.toolCallId) as string | undefined;
	const getToolCalls = (msg: LCMessage): LCMessage["tool_calls"] | undefined =>
		msg.tool_calls ?? (msg.toolCalls as LCMessage["tool_calls"]);

	const toolResults = new Map<string, LCMessage>();
	for (const msg of messages) {
		if (msg.type === "tool") {
			const tcId = getToolCallId(msg);
			if (tcId) toolResults.set(tcId, msg);
		}
	}

	const result: LocalToolCall[] = [];
	for (const msg of messages) {
		const toolCalls = getToolCalls(msg);
		if (
			(msg.type === "ai" || msg.type === "assistant") &&
			Array.isArray(toolCalls) &&
			toolCalls.length > 0
		) {
			for (let i = 0; i < toolCalls.length; i++) {
				const tc = toolCalls[i];
				const tcId = tc.id || `${msg.id}-tc-${i}`;
				const toolMsg = toolResults.get(tcId);
				result.push({
					id: tcId,
					call: { name: tc.name, args: tc.args, id: tc.id },
					result: toolMsg,
					aiMessage: msg,
					index: i,
					state: toolMsg
						? toolMsg.status === "error"
							? "error"
							: "completed"
						: "pending",
				});
			}
		}
	}
	return result;
}

// ---------------------------------------------------------------------------
// Map ToolCallWithResult state to AI Elements component state
// ---------------------------------------------------------------------------

type ToolRenderState =
	| "output-available"
	| "output-error"
	| "approval-requested"
	| "input-available";

function getToolRenderState(
	tc: LocalToolCall,
	isInterrupted: boolean,
): ToolRenderState {
	if (tc.state === "completed") return "output-available";
	if (tc.state === "error") return "output-error";
	// pending
	if (isInterrupted) return "approval-requested";
	return "input-available";
}

function getMcpAppInfoFromToolCall(tc: LocalToolCall): McpAppToolInfo | null {
	const artifact = tc.result?.artifact;
	if (!artifact || typeof artifact !== "object") return null;
	const a = artifact as Record<string, unknown>;
	// Handle both camelCase (Axios/history) and snake_case (stream)
	const resourceUri = (a.mcpAppResourceUri ?? a.mcp_app_resource_uri) as string | undefined;
	const serverId = (a.mcpServerId ?? a.mcp_server_id) as string | undefined;
	if (!resourceUri || !serverId) return null;
	return { resourceUri, serverId };
}

function getStructuredContentFromToolCall(tc: LocalToolCall): Record<string, unknown> | undefined {
	const artifact = tc.result?.artifact;
	if (!artifact || typeof artifact !== "object") return undefined;
	const a = artifact as Record<string, unknown>;
	// Handle both camelCase (Axios/history) and snake_case (stream/langchain-mcp-adapters)
	const sc = a.structuredContent ?? a.structured_content;
	if (sc && typeof sc === "object") return sc as Record<string, unknown>;
	return undefined;
}

function getToolOutputContent(tc: LocalToolCall): unknown {
	if (!tc.result) return undefined;
	const content = tc.result.content;
	if (typeof content === "string") {
		try {
			return JSON.parse(content);
		} catch {
			return content;
		}
	}
	return content;
}

// ---------------------------------------------------------------------------
// Chat page component
// ---------------------------------------------------------------------------

const ChatPage = () => {
	const params = useParams();
	const agentId = params.id as string;
	const threadId = params.threadId as string;
	// Tracks which thread has been initialised. ``useParams`` returns new
	// values on URL change but the component instance is reused, so a plain
	// ``useRef(false)`` would lock out every thread after the first — and the
	// SDK never re-submits, never aborts the old SSE, and after ~5 switches
	// the browser per-origin connection limit freezes the page.
	const initializedThreadRef = useRef<string | null>(null);
	const [threadModel, setThreadModel] = useState<string | undefined>(undefined);
	const [agentArchived, setAgentArchived] = useState(false);
	const [initialValues, setInitialValues] = useState<Record<
		string,
		unknown
	> | null>(null);
	const [rehydratedInterrupt, setRehydratedInterrupt] = useState(false);

	const { mcpServers } = useMcpServersStore();
	const {
		ready: agentReady,
		status: agentStatus,
		disconnectedMcpServers,
		refetch: refetchReady,
	} = useAgentReadiness(agentArchived ? undefined : agentId);

	const {
		customFetch,
		cancel: cancelRun,
		reset: resetRunId,
		fetchActiveRunId,
	} = useRunCancel(threadId);

	const transport = useMemo(
		() =>
			new FetchStreamTransport({
				apiUrl: `${API_BASE_URL}/threads/${threadId}/runs/stream`,
				fetch: customFetch,
			}),
		[threadId, customFetch],
	);

	const thread = useStream<Record<string, unknown>>({
		transport,
		threadId,
		initialValues: initialValues ?? { messages: [] },
		messagesKey: "messages",
		filterSubagentMessages: true,
		onFinish: () => {
			const audio = new Audio("/success.mp3");
			audio.play().catch(() => {});
		},
	} as Parameters<typeof useStream<Record<string, unknown>>>[0]);

	const {
		isLoading,
		error,
		interrupt,
		submit: rawSubmit,
		stop,
	} = thread;

	// Once anything is dispatched, the live stream owns interrupt state — drop
	// the rehydrated fallback so it can't shadow a fresh post-resume answer.
	const submit = useCallback<typeof rawSubmit>(
		(input, opts) => {
			setRehydratedInterrupt(false);
			return rawSubmit(input, opts);
		},
		[rawSubmit],
	);

	// The custom transport path exposes subagent methods at runtime but
	// BaseStream types do not include them. Cast to access the API.
	const subagentApi = thread as unknown as SubagentApi;

	// Coordinator todos from stream values
	const streamValues = thread.values as Record<string, unknown>;
	const coordinatorTodos = (streamValues?.todos ?? []) as Todo[];

	// Messages: use stream messages when available, else initial.
	// Throttle to ~16Hz so streamed chunks don't trigger per-token re-renders
	// of the whole conversation (and per-token markdown re-parses).
	const streamMessagesRaw = thread.messages as LCMessage[];
	const streamMessages = useThrottledValue(streamMessagesRaw, 60);
	const initMessages = (
		initialValues?.messages ?? []
	) as LCMessage[];
	const messages =
		streamMessages.length > 0 || isLoading ? streamMessages : initMessages;

	const isInterrupted = interrupt != null || rehydratedInterrupt;

	// Tool calls: use stream tool calls when streaming, else compute from messages
	// eslint-disable-next-line @typescript-eslint/no-explicit-any
	const streamToolCallsRaw = ((thread as any).toolCalls ?? []) as LocalToolCall[];
	const streamToolCalls = useThrottledValue(streamToolCallsRaw, 60);
	const localToolCalls = useMemo(
		() => computeToolCallsFromMessages(messages),
		[messages],
	);
	const toolCalls =
		streamToolCalls.length > 0 || isLoading ? streamToolCalls : localToolCalls;

	// Index tool calls by AI message id once per render, so the inner map can
	// look them up in O(1) instead of filtering the full list per message.
	const toolCallsByMessageId = useMemo(() => {
		const map = new Map<string, LocalToolCall[]>();
		for (const tc of toolCalls) {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			const id = (tc.aiMessage as any)?.id as string | undefined;
			if (!id || !tc.call.name) continue;
			const existing = map.get(id);
			if (existing) existing.push(tc);
			else map.set(id, [tc]);
		}
		return map;
	}, [toolCalls]);

	const getToolCallsForMessage = useCallback(
		(message: LCMessage) => {
			if (!message.id) return [];
			return toolCallsByMessageId.get(message.id) ?? [];
		},
		[toolCallsByMessageId],
	);

	// Loading state detection
	const lastMsg = messages.length > 0 ? messages[messages.length - 1] : null;
	const isAwaitingResponse =
		isLoading &&
		lastMsg != null &&
		(lastMsg.type === "human" || lastMsg.type === "user");

	const assistantIsStreaming =
		isLoading &&
		lastMsg != null &&
		(lastMsg.type === "ai" || lastMsg.type === "assistant");

	const consumePendingMessage = usePendingMessageStore(
		(state) => state.consumePendingMessage,
	);
	const knownServerNames = [...mcpServers.map((server) => server.name)].sort(
		(a, b) => b.length - a.length,
	);
	const { setCurrentChat, clearCurrentChat } = useChatHeaderStore();

	// ---- Handlers ----

	const handleSubmit = (message: PromptInputMessage) => {
		if (!message) return;

		const hasText = "text" in message && message.text?.trim();
		const hasFiles =
			"files" in message && message.files && message.files.length > 0;

		if (!hasText && !hasFiles) return;

		// Build LangChain content blocks
		const contentParts: Array<Record<string, unknown>> = [];
		if (hasText) contentParts.push({ type: "text", text: message.text });
		for (const file of message.files ?? []) {
			const fileAny = file as Record<string, unknown>;
			const fileUrl = (fileAny.url as string) || "";
			const mediaType = (fileAny.mediaType as string) || "";

			if (mediaType.startsWith("image/")) {
				// Images: standard LangChain image_url block
				contentParts.push({
					type: "image_url",
					image_url: { url: fileUrl, detail: "auto" },
				});
			} else {
				// Non-image files (PDF, etc.): standard LangChain file block
				// LangChain adapters convert this to provider-native format
				const base64Match = fileUrl.match(/^data:[^;]*;base64,(.*)$/);
				const base64Data = base64Match ? base64Match[1] : fileUrl;
				const filename = (fileAny.filename as string) || "file";
				contentParts.push({
					type: "file",
					mime_type: mediaType || "application/octet-stream",
					base64: base64Data,
					filename,
				});
			}
		}

		const content =
			contentParts.length === 1 && contentParts[0].type === "text"
				? (contentParts[0].text as string)
				: contentParts;

		submit(
			{ messages: [{ type: "human", content }] },
			{
				optimisticValues: { messages: [...messages, { type: "human", content, id: crypto.randomUUID() }] },
				streamSubgraphs: true,
			},
		);
	};

	const pendingToolCalls = useMemo(
		() =>
			toolCalls.filter(
				(tc) => getToolRenderState(tc, isInterrupted) === "approval-requested",
			),
		[toolCalls, isInterrupted],
	);

	const { decisions, recordDecision } = useHitlApprovals({
		isInterrupted,
		pendingToolCalls,
		submit,
		messages,
	});

	const handleRegenerate = () => {
		// Find the last human message and resubmit with regenerate trigger
		const lastHuman = [...messages]
			.reverse()
			.find((m) => m.type === "human" || m.type === "user");
		if (!lastHuman) return;

		submit(
			{ messages: [{ type: "human", content: lastHuman.content }] },
			{
				config: {
					configurable: { trigger: "regenerate-message" },
				},
				optimisticValues: { messages },
				streamSubgraphs: true,
			},
		);
	};

	// ---- Fetch subagent internal messages after reconstruction ----

	const hasFetchedSubagentHistory = useRef(false);

	useEffect(() => {
		if (hasFetchedSubagentHistory.current) return;
		if (isLoading) return;
		if (!subagentApi.subagents || subagentApi.subagents.size === 0) return;

		// Find subagents that were reconstructed but have no internal messages
		const toFetch = [...subagentApi.subagents.entries()].filter(
			([, s]) => s.messages.length === 0 && (s.status === "complete" || s.status === "error"),
		);
		if (toFetch.length === 0) return;

		hasFetchedSubagentHistory.current = true;

		// Access the private subagentManager to call updateSubagentFromSubgraphState
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		const streamManager = thread as any;
		const subagentManager = streamManager.subagentManager ?? streamManager._subagentManager;

		Promise.all(
			toFetch.map(async ([toolCallId]) => {
				try {
					const res = await api.get(
						`/threads/${threadId}/subagents/${toolCallId}/state`,
					);
					const msgs = res.data?.messages;
					if (!Array.isArray(msgs) || msgs.length === 0) return;

					if (subagentManager?.updateSubagentFromSubgraphState) {
						subagentManager.updateSubagentFromSubgraphState(toolCallId, msgs);
					} else {
						// Fallback: mutate the subagent entry directly
						const sub = subagentApi.getSubagent(toolCallId);
						if (sub && sub.messages.length === 0) {
							sub.messages = msgs;
						}
					}
				} catch {
					// Subgraph checkpoint may not exist — ignore
				}
			}),
		);
	}, [subagentApi, thread, isLoading, threadId]);

	// ---- Initialization ----

	useEffect(() => {
		return () => clearCurrentChat();
	}, [clearCurrentChat]);

	useEffect(() => {
		if (initializedThreadRef.current === threadId) return;
		initializedThreadRef.current = threadId;

		// Reset per-thread state so the new thread doesn't briefly render the
		// previous thread's checkpoint while ``initializeChat`` re-fetches.
		setInitialValues(null);
		setRehydratedInterrupt(false);
		setAgentArchived(false);
		hasFetchedSubagentHistory.current = false;
		resetRunId();

		const initializeChat = async () => {
			// Race the thread fetch and the active-run probe so we know up
			// front whether we should render the checkpoint or wait for the
			// live replay. Doing them sequentially produces a visible flicker:
			// the checkpoint paints, then the replayed message-mode deltas
			// rebuild the in-flight AI message from "" upwards, briefly
			// shrinking or replacing the already-rendered text.
			const [response, activeRunId] = await Promise.all([
				api.get(`/threads/${threadId}`),
				fetchActiveRunId(),
			]);
			const data = response.data;

			setThreadModel(data.thread.modelId);
			setCurrentChat({
				agentName: data.thread.agentName ?? null,
				agentEmoji: data.thread.agentEmoji ?? null,
				agentColor: data.thread.agentColor ?? null,
				modelId: data.thread.modelId ?? null,
			});

			if (data.thread.agentArchived) {
				setAgentArchived(true);
			}

			if (data.interrupted) {
				setRehydratedInterrupt(true);
			}

			const pendingMessage = consumePendingMessage(threadId);
			if (pendingMessage) {
				// Set initial values first so submit has proper history base
				setInitialValues(data.values || { messages: [] });
				// Defer submit to next tick so initialValues takes effect
				setTimeout(() => {
					handleSubmit(pendingMessage);
				}, 0);
				return;
			}

			if (activeRunId) {
				// Don't render the checkpoint — the replay from last_event_id=0
				// emits ``values``-mode events carrying the full graph state
				// (history + in-flight AI message), so populating from SSE alone
				// avoids the mid-flight rebuild flicker. We still need
				// initialValues set so useStream renders something instead of
				// nothing while the first replay event lands; an empty messages
				// list is harmless and gets replaced almost immediately.
				setInitialValues({ messages: [] });
				setTimeout(() => {
					submit({
						[REATTACH_RUN_ID_KEY]: activeRunId,
					} as Record<string, unknown>);
				}, 0);
				return;
			}

			setInitialValues(data.values || { messages: [] });
		};

		initializeChat();
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [threadId]);

	// ---- Render ----

	return (
		<div className="h-full flex flex-col w-full overflow-hidden">
			<div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
				<Conversation>
					<ConversationContent className="max-w-4xl mx-auto w-full lg:px-10 px-6">
						{coordinatorTodos.length > 0 && (
							<TodoList
								todos={coordinatorTodos}
								className="mb-4 rounded-lg border border-border/50 bg-muted/30 p-4"
							/>
						)}
						{messages.map((message, messageIndex) => {
							// Skip tool messages — they're rendered via toolCalls pairing
							if (message.type === "tool") return null;

							// ---- Human message ----
							if (
								message.type === "human" ||
								message.type === "user"
							) {
								const text = getTextContent(message);
								const attachments = getFileAttachments(message);

								return (
									<Fragment key={message.id ?? messageIndex}>
										{attachments.length > 0 && (
											<div className="flex justify-end">
												<Attachments variant="inline">
													{attachments.map((attachment) => {
														const mediaCategory =
															getMediaCategory(attachment);
														const label = getAttachmentLabel(attachment);
														return (
															<AttachmentHoverCard key={attachment.id}>
																<AttachmentHoverCardTrigger asChild>
																	<Attachment data={attachment}>
																		<div className="relative size-5 shrink-0">
																			<div className="absolute inset-0 transition-opacity group-hover:opacity-0">
																				<AttachmentPreview />
																			</div>
																		</div>
																		<AttachmentInfo />
																	</Attachment>
																</AttachmentHoverCardTrigger>
																<AttachmentHoverCardContent>
																	<div className="space-y-3">
																		{mediaCategory === "image" &&
																			"url" in attachment &&
																			attachment.url && (
																				<div className="flex items-center justify-center overflow-hidden rounded-md border">
																					<Image
																						alt={label}
																						className="object-contain"
																						height={200}
																						src={
																							attachment.url as string
																						}
																						width={200}
																					/>
																				</div>
																			)}
																		<div className="space-y-1 px-0.5">
																			<h4 className="font-semibold text-sm leading-none">
																				{label}
																			</h4>
																		</div>
																	</div>
																</AttachmentHoverCardContent>
															</AttachmentHoverCard>
														);
													})}
												</Attachments>
											</div>
										)}
										{text && (
											<Message from="user">
												<MessageContent>
													<MessageResponse>{text}</MessageResponse>
												</MessageContent>
											</Message>
										)}
									</Fragment>
								);
							}

							// ---- AI message ----
							if (
								message.type === "ai" ||
								message.type === "assistant"
							) {
								const text = getTextContent(message);
								const reasoning = getReasoningContent(message);
								const msgToolCalls = getToolCallsForMessage(message);
								const isLastMessage =
									messageIndex === messages.length - 1 ||
									// Last AI message before a potential loading indicator
									(messageIndex === messages.length - 2 &&
										messages[messages.length - 1]?.type === "tool");
								const isLastAiMessage =
									!isLoading && isLastMessage && text.length > 0;

								return (
									<Fragment key={message.id ?? messageIndex}>
										{/* Reasoning / thinking */}
										{reasoning && (
											<Reasoning
												className="w-full"
												isStreaming={
													assistantIsStreaming && isLastMessage
												}
											>
												<ReasoningTrigger />
												<ReasoningContent>{reasoning}</ReasoningContent>
											</Reasoning>
										)}

										{/* Text content */}
										{text && (
											<>
												<Message from="assistant">
													<MessageContent>
														<MessageResponse>{text}</MessageResponse>
													</MessageContent>
												</Message>
												{isLastAiMessage && (
													<MessageActions>
														<MessageAction
															onClick={handleRegenerate}
															label="Retry"
														>
															<RefreshCcwIcon className="size-3" />
														</MessageAction>
														<MessageAction
															onClick={() =>
																navigator.clipboard.writeText(text)
															}
															label="Copy"
														>
															<CopyIcon className="size-3" />
														</MessageAction>
													</MessageActions>
												)}
											</>
										)}

										{/* Tool calls */}
										{msgToolCalls.map((tc) => {
											const toolState = getToolRenderState(tc, isInterrupted);
											const { serverName, toolName } = getToolMetadata(
												tc.call.name,
												knownServerNames,
											);
											const output = getToolOutputContent(tc);

											const decided = decisions[tc.id];

											return (
												<Fragment key={tc.id}>
													<Tool
														toolState={toolState}
														lockOpen={
															toolState === "approval-requested" && !decided
														}
													>
														<ToolHeader
															title={toolName}
															type={`tool-${tc.call.name}`}
															state={toolState}
															mcpServerName={serverName}
															mcpServerIcon={
																mcpServers.find(
																	(server) =>
																		server.name === serverName,
																)?.iconUrl
															}
														/>
														<ToolContent>
															<ToolContentInner>
																{tc.call.args !== undefined && (
																	<ToolInput input={tc.call.args} />
																)}
																{(output !== undefined ||
																	tc.state === "error" ||
																	tc.state === "pending") && (
																	<ToolOutput
																		output={
																			output as React.ReactNode
																		}
																		errorText={
																			tc.state === "error" &&
																			tc.result
																				? (typeof tc.result
																						.content === "string"
																						? tc.result.content
																						: "Tool execution failed")
																				: undefined
																		}
																	/>
																)}
															</ToolContentInner>
															{/* HITL Approval UI */}
															{toolState ===
																"approval-requested" && (
																<ToolFooter>
																	<Button
																		variant="default"
																		className={cn(
																			"cursor-pointer",
																			decided === "reject" && "opacity-40",
																		)}
																		disabled={decided != null}
																		onClick={() =>
																			recordDecision(tc.id, "approve")
																		}
																	>
																		Approve
																	</Button>
																	<Button
																		variant="ghost"
																		className={cn(
																			"cursor-pointer",
																			decided === "approve" && "opacity-40",
																		)}
																		disabled={decided != null}
																		onClick={() =>
																			recordDecision(tc.id, "reject")
																		}
																	>
																		Reject
																	</Button>
																</ToolFooter>
															)}
														</ToolContent>
													</Tool>
													{(() => {
														const appToolInfo = getMcpAppInfoFromToolCall(tc);
														if (!appToolInfo) return null;
														return (
															<McpAppWidget
																input={tc.call.args}
																output={getToolOutputContent(tc)}
																structuredContent={getStructuredContentFromToolCall(tc)}
																errorText={
																	tc.state === "error" && tc.result
																		? typeof tc.result.content === "string"
																			? tc.result.content
																			: "Tool execution failed"
																		: undefined
																}
																toolName={toolName}
																appToolInfo={appToolInfo}
															/>
														);
													})()}
												</Fragment>
											);
										})}

										{/* Subagent cards */}
										{(() => {
											const turnSubagents = message.id
												? subagentApi.getSubagentsByMessage(message.id)
												: [];
											if (turnSubagents.length === 0) return null;
											return (
												<div className="space-y-2 mt-1">
													<SubAgentProgress subagents={turnSubagents} />
													{turnSubagents.map((sub) => (
														<SubAgentCard key={sub.id} subagent={sub} mcpServers={mcpServers} />
													))}
													<SynthesisIndicator
														subagents={turnSubagents}
														isCoordinatorStreaming={
															assistantIsStreaming && isLastMessage
														}
													/>
												</div>
											);
										})()}
									</Fragment>
								);
							}

							return null;
						})}

						{/* Loading indicator */}
						{isAwaitingResponse && (
							<div>
								<Message from="assistant">
									<div className="w-full flex flex-col gap-2">
										<MessageContent>
											<ThinkingLoader className="px-0" />
										</MessageContent>
									</div>
								</Message>
							</div>
						)}

						{/* Streaming indicator when AI has started but text is still coming */}
						{assistantIsStreaming &&
							lastMsg !== null &&
							getTextContent(lastMsg).length === 0 &&
							!getToolCallsForMessage(lastMsg).length && (
								<div>
									<Message from="assistant">
										<div className="w-full flex flex-col gap-2">
											<MessageContent>
												<ThinkingLoader className="px-0" />
											</MessageContent>
										</div>
									</Message>
								</div>
							)}

						{error != null && (
							<Error>
								<ErrorContent>An error occurred.</ErrorContent>
								<ErrorDetails>
									<div>
										{error instanceof globalThis.Error
											? error.message
											: String(error)}
									</div>
								</ErrorDetails>
							</Error>
						)}
					</ConversationContent>
					<ConversationScrollButton />
				</Conversation>
				<div className="pointer-events-none absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-background to-transparent z-10" />
			</div>
			<div className="w-full shrink-0 bg-background">
				{agentArchived ? (
					<div className="w-full max-w-4xl mx-auto lg:px-10 px-6 py-6">
						<div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
							<ArchiveIcon className="size-5 shrink-0 text-muted-foreground" />
							<p className="text-sm text-muted-foreground">
								The agent linked to this conversation has been archived. This
								thread is preserved as read-only so you can still review your
								past messages.
							</p>
						</div>
					</div>
				) : agentStatus === "not_configured" ? (
					<div className="w-full max-w-4xl mx-auto lg:px-10 px-6 py-4">
						<div className="w-full flex items-center justify-center border border-red-200 bg-red-50 rounded-lg px-4 py-8">
							<p className="text-md text-center text-red-700">
								Agent is not configured yet. Contact agent owner to configure it
								first.
							</p>
						</div>
					</div>
				) : (
					<ChatPromptInput
						onSubmit={handleSubmit}
						status={isLoading ? "streaming" : "ready"}
						className="w-full max-w-4xl mx-auto lg:px-10 px-6 py-4"
						stop={() => {
							// Fire-and-forget the server-side cancel so the worker
							// stops burning tokens; tear down the local stream
							// immediately for a snappy Stop button.
							cancelRun().catch(() => {});
							resetRunId();
							stop();
						}}
						selectedModel={threadModel}
						readOnlyModel={true}
						agentReady={agentReady}
						disconnectedServers={disconnectedMcpServers}
						onAllConnected={refetchReady}
					/>
				)}
			</div>
		</div>
	);
};

export default ChatPage;

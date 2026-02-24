"use client";

import { Fragment, useEffect, useRef, useState } from "react";
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
import ChatPromptInput from "../components/prompt-input";
import { RefreshCcwIcon, CopyIcon } from "lucide-react";
import { useChat } from "@ai-sdk/react";
import {
	DefaultChatTransport,
	type ToolUIPart,
	lastAssistantMessageIsCompleteWithApprovalResponses,
} from "ai";
import { useParams } from "next/navigation";
import { api, API_BASE_URL } from "@/lib/api/client";
import { Loader } from "../components/loader";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useAgentReadiness } from "@/hooks/use-agent-readiness";
import { useChatHeaderStore } from "@/stores/chat-header-store";

const ChatPage = () => {
	const params = useParams();
	const agentId = params.id as string;
	const threadId = params.threadId as string;
	const hasInitialized = useRef(false);
	const [threadModel, setThreadModel] = useState<string | undefined>(undefined);
	const { mcpServers } = useMcpServersStore();
	const {
		ready: agentReady,
		status: agentStatus,
		disconnectedMcpServers,
		refetch: refetchReady,
	} = useAgentReadiness(agentId);
	const {
		messages,
		sendMessage,
		status,
		setMessages,
		regenerate,
		error,
		stop,
		addToolApprovalResponse,
	} = useChat({
		transport: new DefaultChatTransport({
			api: `${API_BASE_URL}/threads/${threadId}/invoke`,
			prepareSendMessagesRequest: ({ messages, trigger, messageId }) => {
				const message = messages[messages.length - 1];
				return {
					body: {
						messages: [message],
						trigger,
						messageId,
					},
				};
			},
		}),
		sendAutomaticallyWhen: lastAssistantMessageIsCompleteWithApprovalResponses,
		onFinish: () => {
			const audio = new Audio("/success.mp3");
			audio.play().catch(() => {});
		},
	});

	const isAwaitingResponse =
		status === "submitted" ||
		(status === "streaming" &&
			messages.length > 0 &&
			!messages[messages.length - 1].parts.some(
				(p) => p.type === "text" && p.text.length > 0,
			));

	const consumePendingMessage = usePendingMessageStore(
		(state) => state.consumePendingMessage,
	);
	const { setCurrentChat, clearCurrentChat } = useChatHeaderStore();

	const handleSubmit = (message: PromptInputMessage) => {
		if (!message) return;

		const hasText = "text" in message && message.text?.trim();
		const hasFiles =
			"files" in message && message.files && message.files.length > 0;

		if (hasText || hasFiles) {
			sendMessage(message as Parameters<typeof sendMessage>[0]);
		}
	};

	useEffect(() => {
		return () => clearCurrentChat();
	}, [clearCurrentChat]);

	useEffect(() => {
		if (hasInitialized.current) return;

		hasInitialized.current = true;

		const initializeChat = async () => {
			const response = await api.get(`/threads/${threadId}`);
			const data = response.data;

			setThreadModel(data.thread.modelId);
			setCurrentChat({
				agentName: data.thread.agentName ?? null,
				agentEmoji: data.thread.agentEmoji ?? null,
				modelId: data.thread.modelId ?? null,
			});

			const pendingMessage = consumePendingMessage(threadId);
			if (pendingMessage) {
				sendMessage(pendingMessage as Parameters<typeof sendMessage>[0]);
			} else {
				setMessages(data.messages);
			}
		};

		initializeChat();
	}, [threadId, setMessages, sendMessage, consumePendingMessage]);

	return (
		<div className="h-full flex flex-col w-full overflow-hidden">
			<div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
				<Conversation>
					<ConversationContent className="max-w-4xl mx-auto w-full lg:px-10 px-6">
						{messages.map((message, messageIndex) => {
							// Group all file parts together
							const fileParts = message.parts
								.map((part, i) => ({ part, index: i }))
								.filter(({ part }) => part.type === "file");
							const otherParts = message.parts
								.map((part, i) => ({ part, index: i }))
								.filter(({ part }) => part.type !== "file");

							// Convert file parts to attachment data
							const attachments: AttachmentData[] = fileParts.map(
								({ part, index }) => {
									const filePart = part as {
										type: "file";
										url: string;
										filename?: string;
										mediaType?: string;
									};
									const isImage = filePart.mediaType?.includes("image");
									const renderUrl = isImage
										? filePart.url.startsWith("data:")
											? filePart.url
											: `data:image/jpeg;base64,${filePart.url}`
										: filePart.url;

									return {
										id: `${message.id}-${index}`,
										url: renderUrl,
										type: "file" as const,
										filename:
											filePart.filename ||
											(isImage ? "Image.jpg" : "Attachment"),
										mediaType: isImage
											? filePart.mediaType || "image/jpeg"
											: filePart.mediaType || "application/octet-stream",
									};
								},
							);

							return (
								<Fragment key={message.id}>
									{/* Render all file attachments together */}
									{attachments.length > 0 && (
										<div className="flex justify-end">
											<Attachments variant="inline">
												{attachments.map((attachment) => {
													const mediaCategory = getMediaCategory(attachment);
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
																		attachment.type === "file" &&
																		attachment.url && (
																			<div className="flex items-center justify-center overflow-hidden rounded-md border">
																				<Image
																					alt={label}
																					className="object-contain"
																					height={200}
																					src={attachment.url}
																					width={200}
																				/>
																			</div>
																		)}
																	<div className="space-y-1 px-0.5">
																		<h4 className="font-semibold text-sm leading-none">
																			{label}
																		</h4>
																		{attachment.mediaType && (
																			<p className="font-mono text-muted-foreground text-xs">
																				{attachment.mediaType}
																			</p>
																		)}
																	</div>
																</div>
															</AttachmentHoverCardContent>
														</AttachmentHoverCard>
													);
												})}
											</Attachments>
										</div>
									)}

									{/* Render other parts */}
									{otherParts.map(({ part, index: i }) => {
										switch (part.type) {
											case "text":
												const isLastMessagePart =
													i === message.parts.length - 1 &&
													messageIndex === messages.length - 1 &&
													status !== "streaming";

												return (
													<Fragment key={`${message.id}-${i}`}>
														<Message from={message.role}>
															<MessageContent>
																<MessageResponse>{part.text}</MessageResponse>
															</MessageContent>
														</Message>
														{message.role === "assistant" &&
															isLastMessagePart && (
																<MessageActions>
																	<MessageAction
																		onClick={() => regenerate()}
																		label="Retry"
																	>
																		<RefreshCcwIcon className="size-3" />
																	</MessageAction>
																	<MessageAction
																		onClick={() =>
																			navigator.clipboard.writeText(part.text)
																		}
																		label="Copy"
																	>
																		<CopyIcon className="size-3" />
																	</MessageAction>
																</MessageActions>
															)}
													</Fragment>
												);
											case "reasoning":
												// Check if this specific reasoning part is still being streamed
												// This should be true only when this reasoning part is actively being written to
												const isReasoningStreaming =
													status === "streaming" &&
													messageIndex === messages.length - 1 &&
													i === message.parts.length - 1;

												return (
													<Reasoning
														key={`${message.id}-${i}`}
														className="w-full"
														isStreaming={isReasoningStreaming}
													>
														<ReasoningTrigger />
														<ReasoningContent>{part.text}</ReasoningContent>
													</Reasoning>
												);
											default:
												if (part.type.startsWith("tool-")) {
													const toolPart = part as ToolUIPart;
													const serverName = part.type
														.split("_")[0]
														.replace("tool-", "");
													const toolName = part.type
														.split("_")
														.slice(1)
														.join("_");

													return (
														<Tool
															key={`${message.id}-${i}`}
															toolState={toolPart.state}
														>
															<ToolHeader
																title={toolName}
																type={toolPart.type}
																state={toolPart.state}
																approval={toolPart.approval}
																mcpServerName={serverName}
																mcpServerIcon={
																	mcpServers.find(
																		(server) => server.name === serverName,
																	)?.iconUrl
																}
															/>
															<ToolContent>
																<ToolContentInner>
																	{toolPart.input !== undefined && (
																		<ToolInput input={toolPart.input} />
																	)}
																	{/* Show output, error, or optimistic rejection message */}
																	{(toolPart.output ||
																		toolPart.errorText ||
																		toolPart.state === "input-available" ||
																		toolPart.state === "input-streaming" ||
																		(toolPart.state === "approval-responded" &&
																			toolPart.approval?.approved ===
																				false)) && (
																		<ToolOutput
																			output={
																				toolPart.output as React.ReactNode
																			}
																			errorText={
																				toolPart.errorText ||
																				(toolPart.state ===
																					"approval-responded" &&
																				toolPart.approval?.approved === false
																					? "Tool execution was rejected by user"
																					: undefined)
																			}
																		/>
																	)}
																</ToolContentInner>
																{/* Tool Approval UI */}
																{toolPart.state === "approval-requested" && (
																	<ToolFooter>
																		<Button
																			variant="default"
																			className="cursor-pointer"
																			onClick={() => {
																				addToolApprovalResponse({
																					id: toolPart.approval.id,
																					approved: true,
																				});
																			}}
																		>
																			Approve
																		</Button>
																		<Button
																			variant="ghost"
																			className="cursor-pointer"
																			onClick={() => {
																				addToolApprovalResponse({
																					id: toolPart.approval.id,
																					approved: false,
																				});
																			}}
																		>
																			Reject
																		</Button>
																	</ToolFooter>
																)}
															</ToolContent>
														</Tool>
													);
												}
												return null;
										}
									})}
								</Fragment>
							);
						})}

						{isAwaitingResponse && (
							<div>
								<Message from="assistant">
									<div className="w-full flex flex-col gap-2">
										<MessageContent>
											<Loader className="px-0" />
										</MessageContent>
									</div>
								</Message>
							</div>
						)}

						{error && (
							<Error>
								<ErrorContent>An error occurred.</ErrorContent>
								<ErrorDetails>
									<div>{error.message}</div>
								</ErrorDetails>
							</Error>
						)}
					</ConversationContent>
					<ConversationScrollButton />
				</Conversation>
			</div>
			<div className="w-full shrink-0 bg-background">
				{agentStatus === "not_configured" ? (
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
						status={status === "streaming" ? "streaming" : "ready"}
						className="w-full max-w-4xl mx-auto lg:px-10 px-6 py-4"
						stop={stop}
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

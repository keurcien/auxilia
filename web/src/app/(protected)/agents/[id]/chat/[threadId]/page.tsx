"use client";

import { Fragment, useEffect, useRef, useState } from "react";
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
import { api } from "@/lib/api/client";
import { Loader } from "../components/loader";
import { useMcpServersStore } from "@/stores/mcp-servers-store";

const ChatPage = () => {
	const params = useParams();
	const threadId = params.threadId as string;
	const hasInitialized = useRef(false);
	const [threadModel, setThreadModel] = useState<string | undefined>(undefined);
	const [isAwaitingResponse, setIsAwaitingResponse] = useState(false);
	const { mcpServers } = useMcpServersStore();
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
			api: `http://localhost:8000/threads/${threadId}/invoke`,
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
			setIsAwaitingResponse(false);
			const audio = new Audio("/success.mp3");
			audio.play().catch(() => {});
		},
	});

	const handleSubmit = (message: PromptInputMessage) => {
		if (message && "text" in message && message.text?.trim()) {
			sendMessage({ text: message.text });
		}
	};

	useEffect(() => {
		if (hasInitialized.current) return;

		hasInitialized.current = true;

		const initializeChat = async () => {
			const response = await api.get(`/threads/${threadId}`);
			const data = response.data;

			setThreadModel(data.thread.modelId);

			if (data.thread?.firstMessageContent && data.messages.length === 0) {
				sendMessage({ text: data.thread.firstMessageContent });
			} else {
				setMessages(data.messages);
				console.log(data.messages);
			}
		};

		initializeChat();
	}, [threadId, setMessages, sendMessage]);

	// Track when we're awaiting the first token
	useEffect(() => {
		if (status === "submitted") {
			setIsAwaitingResponse(true);
		}
	}, [status]);

	return (
		<div className="h-full flex flex-col w-full overflow-hidden">
			<div className="h-full relative flex flex-1 flex-col min-h-0 w-full">
				<Conversation>
					<ConversationContent className="max-w-4xl mx-auto w-full lg:px-10 px-6">
						{messages.map((message, messageIndex) => (
							<Fragment key={message.id}>
								{message.parts.map((part, i) => {
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
													<Tool key={`${message.id}-${i}`} defaultOpen={false}>
														<ToolHeader
															title={toolName}
															type={toolPart.type}
															state={toolPart.state}
															approval={toolPart.approval}
															mcpServerName={serverName}
															mcpServerIcon={
																mcpServers.find(
																	(server) => server.name === serverName
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
																		toolPart.approval?.approved === false)) && (
																	<ToolOutput
																		output={toolPart.output as React.ReactNode}
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
						))}

						{(status === "submitted" ||
							(status === "streaming" && isAwaitingResponse)) && (
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
				<ChatPromptInput
					onSubmit={handleSubmit}
					status={status === "streaming" ? "streaming" : "ready"}
					className="w-full max-w-4xl mx-auto lg:px-10 px-6 py-4"
					stop={stop}
					selectedModel={threadModel}
					readOnlyModel={true}
				/>
			</div>
		</div>
	);
};

export default ChatPage;

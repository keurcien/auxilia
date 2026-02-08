"use client";

import { cn } from "@/lib/utils";
import {
	ModelSelector,
	ModelSelectorContent,
	ModelSelectorEmpty,
	ModelSelectorGroup,
	ModelSelectorInput,
	ModelSelectorItem,
	ModelSelectorList,
	ModelSelectorLogo,
	ModelSelectorName,
	ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import {
	PromptInput,
	PromptInputAddAttachmentButton,
	PromptInputAttachment,
	PromptInputAttachments,
	PromptInputBody,
	PromptInputButton,
	PromptInputFooter,
	type PromptInputMessage,
	PromptInputProvider,
	PromptInputTextarea,
	PromptInputTools,
	usePromptInputController,
} from "@/components/ai-elements/prompt-input";
import { CheckIcon, PlugIcon } from "lucide-react";
import { useRef, useState, useEffect, useMemo } from "react";
import { useModelsStore } from "@/stores/models-store";
import { Model } from "@/types/models";
import { MCPServer } from "@/types/mcp-servers";
import { ConnectServersDialog } from "./connect-servers-dialog";

interface ChatPromptInputProps {
	onSubmit: (message: PromptInputMessage) => void;
	status: "submitted" | "streaming" | "ready" | "error";
	className?: string;
	stop?: () => void;
	onModelChange?: (modelId: string) => void;
	selectedModel?: string;
	readOnlyModel?: boolean;
	agentReady?: boolean | null;
	disconnectedServers?: MCPServer[];
	onAllConnected?: () => void;
}

const ChatPromptInput = ({
	onSubmit,
	status,
	className,
	stop,
	onModelChange,
	selectedModel: externalSelectedModel,
	readOnlyModel = false,
	agentReady,
	disconnectedServers = [],
	onAllConnected,
}: ChatPromptInputProps) => {
	const [connectDialogOpen, setConnectDialogOpen] = useState(false);
	const models = useModelsStore((state) => state.models);
	const fetchModels = useModelsStore((state) => state.fetchModels);
	const [model, setModel] = useState<string | undefined>(undefined);
	const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	const currentModel = externalSelectedModel ?? model;
	const selectedModelData = models.find((m) => m.id === currentModel);

	const handleModelChange = (modelId: string) => {
		setModel(modelId);
		onModelChange?.(modelId);
	};

	const groupedModels = useMemo(() => {
		return models.reduce(
			(acc, model) => {
				acc[model.chef] = acc[model.chef] || [];
				acc[model.chef].push(model);
				return acc;
			},
			{} as Record<string, Model[]>,
		);
	}, [models]);

	const handleSubmit = (message: PromptInputMessage) => {
		if (!message) return;

		const hasText = Boolean("text" in message && message.text);
		const hasAttachments = Boolean("files" in message && message.files?.length);
		console.log("hasText", hasText, "hasAttachments", hasAttachments);
		if (!(hasText || hasAttachments)) {
			return;
		}
		onSubmit(message);
	};

	useEffect(() => {
		// Only fetch if we don't have models yet
		if (models.length === 0) {
			fetchModels();
		}
	}, [fetchModels, models.length]);

	return (
		<PromptInputProvider>
			<PromptInput
				globalDrop
				multiple
				onSubmit={handleSubmit}
				className={cn("min-h-40 transition-all duration-200", className)}
			>
				<PromptInputAttachments>
					{(attachment) => <PromptInputAttachment data={attachment} />}
				</PromptInputAttachments>
				<PromptInputBody>
					<PromptInputTextarea ref={textareaRef} />
				</PromptInputBody>
				<PromptInputFooter>
					<PromptInputTools>
						<PromptInputAddAttachmentButton />
						{/* <PromptInputSpeechButton textareaRef={textareaRef} />
						<PromptInputButton>
							<GlobeIcon size={16} />
							<span>Search</span>
						</PromptInputButton> */}
						{readOnlyModel ? (
							<PromptInputButton disabled>
								{selectedModelData?.chefSlug && (
									<ModelSelectorLogo provider={selectedModelData.chefSlug} />
								)}
								{selectedModelData?.name && (
									<ModelSelectorName>
										{selectedModelData.name}
									</ModelSelectorName>
								)}
							</PromptInputButton>
						) : (
							<ModelSelector
								onOpenChange={setModelSelectorOpen}
								open={modelSelectorOpen}
							>
								<ModelSelectorTrigger asChild>
									<PromptInputButton>
										{selectedModelData ? (
											<>
												<ModelSelectorLogo
													provider={selectedModelData.chefSlug}
												/>
												<ModelSelectorName>
													{selectedModelData.name}
												</ModelSelectorName>
											</>
										) : (
											<>
												<ModelSelectorName className="text-muted-foreground">
													Select model
												</ModelSelectorName>
											</>
										)}
									</PromptInputButton>
								</ModelSelectorTrigger>
								<ModelSelectorContent>
									<ModelSelectorInput placeholder="Search models..." />
									<ModelSelectorList>
										<ModelSelectorEmpty>No models found.</ModelSelectorEmpty>

										{Object.entries(groupedModels).map(
											([chefName, chefModels]) => (
												<ModelSelectorGroup heading={chefName} key={chefName}>
													{chefModels.map((m) => (
														<ModelSelectorItem
															key={m.id}
															onSelect={() => {
																handleModelChange(m.id);
																setModelSelectorOpen(false);
															}}
															value={m.id}
														>
															<ModelSelectorLogo provider={m.chefSlug} />
															<ModelSelectorName>{m.name}</ModelSelectorName>

															{currentModel === m.id ? (
																<CheckIcon className="ml-auto size-4" />
															) : (
																<div className="ml-auto size-4" />
															)}
														</ModelSelectorItem>
													))}
												</ModelSelectorGroup>
											),
										)}
									</ModelSelectorList>
								</ModelSelectorContent>
							</ModelSelector>
						)}
					</PromptInputTools>
					{agentReady === false ? (
						<ConnectButton onClick={() => setConnectDialogOpen(true)} />
					) : (
						<SubmitButton status={status} stop={stop} />
					)}
				</PromptInputFooter>
			</PromptInput>
			<ConnectServersDialog
				open={connectDialogOpen}
				onOpenChange={setConnectDialogOpen}
				disconnectedServers={disconnectedServers}
				onAllConnected={() => onAllConnected?.()}
			/>
		</PromptInputProvider>
	);
};

const SubmitButton = ({
	status,
	stop,
}: {
	status: "submitted" | "streaming" | "ready" | "error";
	stop?: () => void;
}) => {
	const controller = usePromptInputController();
	const input = controller.textInput.value;
	const isStreaming = status === "streaming";
	const isDisabled = isStreaming ? false : !input.trim();

	return (
		<button
			type={isStreaming ? "button" : "submit"}
			disabled={isDisabled}
			onClick={(e) => {
				if (isStreaming && stop) {
					e.preventDefault();
					stop();
				}
			}}
			className={cn(
				"flex items-center justify-center rounded-full w-10 h-10 transition-all",
				isDisabled
					? "bg-gray-200 dark:bg-gray-800 text-gray-400 dark:text-gray-600 cursor-not-allowed"
					: "bg-black dark:bg-white text-white font-bold dark:text-black hover:scale-105 cursor-pointer",
			)}
		>
			{isStreaming ? (
				<svg
					width="20"
					height="20"
					viewBox="0 0 20 20"
					fill="currentColor"
					xmlns="http://www.w3.org/2000/svg"
				>
					<rect x="5" y="5" width="10" height="10" rx="2" />
				</svg>
			) : (
				<svg
					width="20"
					height="20"
					viewBox="0 0 20 20"
					fill="currentColor"
					xmlns="http://www.w3.org/2000/svg"
				>
					<path d="M8.99992 16V6.41407L5.70696 9.70704C5.31643 10.0976 4.68342 10.0976 4.29289 9.70704C3.90237 9.31652 3.90237 8.6835 4.29289 8.29298L9.29289 3.29298L9.36907 3.22462C9.76184 2.90427 10.3408 2.92686 10.707 3.29298L15.707 8.29298L15.7753 8.36915C16.0957 8.76192 16.0731 9.34092 15.707 9.70704C15.3408 10.0732 14.7618 10.0958 14.3691 9.7754L14.2929 9.70704L10.9999 6.41407V16C10.9999 16.5523 10.5522 17 9.99992 17C9.44764 17 8.99992 16.5523 8.99992 16Z" />
				</svg>
			)}
		</button>
	);
};

const ConnectButton = ({ onClick }: { onClick: () => void }) => {
	return (
		<button
			type="button"
			onClick={onClick}
			className={cn(
				"flex items-center gap-2 rounded-full px-4 h-10 transition-all cursor-pointer",
				"bg-black text-white font-medium hover:bg-gray-800",
			)}
		>
			<PlugIcon size={16} />
			<span>Connect</span>
		</button>
	);
};

export default ChatPromptInput;

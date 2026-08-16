"use client";

import { cn } from "@/lib/utils";
import { ModelSelectorLogo } from "@/components/ai-elements/model-selector";
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
} from "@/components/ai-elements/prompt-input";
import { CheckIcon, PlugIcon } from "lucide-react";
import { useRef, useState, useEffect, useMemo } from "react";
import { useModelsStore } from "@/stores/models-store";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { Model } from "@/types/models";
import { MCPServer } from "@/types/mcp-servers";
import { ConnectServersDialog } from "./connect-servers-dialog";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";
import {
	Dialog,
	DialogContent,
	DialogTitle,
	DialogTrigger,
} from "@/components/ui/dialog";
import { SearchBar } from "@/components/ui/search-bar";

// Petrol Mono composer pills: 34px tall, 999px radius, on the hover tint.
const composerPillClass = cn(
	"h-[34px] px-3 gap-2 rounded-full",
	"text-[13px] font-medium text-foreground",
	"bg-hover dark:bg-white/5",
	"hover:bg-petrol-tint dark:hover:bg-white/10",
	"data-[state=open]:bg-petrol-tint dark:data-[state=open]:bg-white/10",
	"disabled:opacity-60 disabled:cursor-not-allowed",
	"transition-colors",
);

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
	const agentName = useChatHeaderStore((state) => state.agentName);
	const [model, setModel] = useState<string | undefined>(undefined);
	const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
	const [modelSearch, setModelSearch] = useState("");
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	const currentModel = externalSelectedModel ?? model;
	const selectedModelData = models.find((m) => m.id === currentModel);
	// Text-only providers can't take image attachments (DeepSeek, Z.ai/GLM 5.2).
	const noAttachments = ["deepseek", "z-ai"].includes(
		selectedModelData?.chefSlug ?? "",
	);

	const handleModelChange = (modelId: string) => {
		setModel(modelId);
		onModelChange?.(modelId);
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

	const handleSubmit = (message: PromptInputMessage) => {
		if (!message) return;

		const hasText = Boolean("text" in message && message.text);
		const hasAttachments = Boolean("files" in message && message.files?.length);
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
		<>
			<PromptInput
				globalDrop
				multiple
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
					"[&>[data-slot=input-group]:focus-within]:border-petrol",
					// Remove default focus ring
					"[&>[data-slot=input-group]]:has-[[data-slot=input-group-control]:focus-visible]:ring-0",
					className,
				)}
			>
				<PromptInputAttachments className="px-[18px] pt-4">
					{(attachment) => <PromptInputAttachment data={attachment} />}
				</PromptInputAttachments>
				<PromptInputBody>
					<PromptInputTextarea
						ref={textareaRef}
						disabled={agentReady === false}
						placeholder={agentName ? `Reply to ${agentName}…` : "Ask anything…"}
						className={cn(
							"text-[15px] font-medium leading-relaxed",
							"text-foreground",
							"placeholder:text-meta dark:placeholder:text-panel-dim",
							"px-[18px] pt-4 pb-2",
						)}
					/>
				</PromptInputBody>
				<PromptInputFooter className="px-3 pt-0 pb-3">
					<PromptInputTools className="gap-1.5">
						{noAttachments ? (
							<Tooltip>
								<TooltipTrigger asChild>
									<span>
										<PromptInputAddAttachmentButton
											disabled
											className={cn(composerPillClass, "w-[34px] px-0")}
										/>
									</span>
								</TooltipTrigger>
								<TooltipContent>
									This model does not support attachments.
								</TooltipContent>
							</Tooltip>
						) : (
							<PromptInputAddAttachmentButton
								disabled={agentReady === false}
								className={cn(
									composerPillClass,
									"w-[34px] px-0 text-subtle dark:text-panel-body",
								)}
							/>
						)}
						{readOnlyModel ? (
							<PromptInputButton disabled className={composerPillClass}>
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
									<PromptInputButton className={composerPillClass}>
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
								<DialogContent className="gap-0 p-0">
									<div className="px-6 pt-6 pb-4">
										<DialogTitle className="text-[16px] leading-snug font-bold text-ink dark:text-panel-button">
											Select a model
										</DialogTitle>
										<p className="mt-1.5 text-[13px] leading-[1.5] text-label dark:text-panel-dim">
											Choose the model powering this chat
										</p>
									</div>

									<div className="px-6 pb-3">
										<SearchBar
											placeholder="Search models..."
											value={modelSearch}
											onChange={setModelSearch}
										/>
									</div>

									<div className="px-4 pb-5 max-h-[55vh] overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
										{!hasModelResults ? (
											<div className="px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
												No models found.
											</div>
										) : (
											Object.entries(groupedModels).map(
												([chefName, chefModels]) => (
													<div key={chefName} className="px-2 pt-2">
														<div className="px-3 pb-1.5 font-mono text-[10px] font-semibold uppercase tracking-[0.09em] text-meta dark:text-panel-dim">
															{chefName}
														</div>
														<div className="flex flex-col gap-0.5">
															{chefModels.map((m) => {
																const isActive = currentModel === m.id;
																return (
																	<button
																		key={m.id}
																		type="button"
																		onClick={() => {
																			handleModelChange(m.id);
																			handleModelSelectorOpenChange(false);
																		}}
																		className={cn(
																			"flex w-full items-center gap-3 px-3 py-2.5 rounded-lg cursor-pointer transition-colors text-left outline-none",
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
					</PromptInputTools>
					{agentReady === false ? (
						<ConnectButton
							onClick={() => {
								setConnectDialogOpen(true);
							}}
						/>
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
		</>
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
				"flex size-[38px] items-center justify-center rounded-full transition-all",
				isDisabled
					? "cursor-not-allowed bg-hover text-ghost dark:bg-white/5 dark:text-panel-dim"
					: "cursor-pointer bg-petrol text-white shadow-submit hover:opacity-90",
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
				"flex h-[38px] cursor-pointer items-center gap-2 rounded-full px-4 transition-all",
				"text-[14px] font-semibold",
				"bg-petrol text-white hover:opacity-90",
				"shadow-submit",
			)}
		>
			<PlugIcon size={16} />
			<span>Connect</span>
		</button>
	);
};

export default ChatPromptInput;

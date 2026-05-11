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

const sagePromptToolButtonClass = cn(
	"h-9 px-3 gap-2 rounded-full",
	"font-[family-name:var(--font-dm-sans)] text-[13px] font-medium",
	"text-[#1E2D28] dark:text-white/90",
	"bg-[#F5F8F6] dark:bg-white/5",
	"hover:bg-[#EDF4F0] dark:hover:bg-white/10",
	"data-[state=open]:bg-[#EDF4F0] dark:data-[state=open]:bg-white/10",
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
	const [model, setModel] = useState<string | undefined>(undefined);
	const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
	const [modelSearch, setModelSearch] = useState("");
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	const currentModel = externalSelectedModel ?? model;
	const selectedModelData = models.find((m) => m.id === currentModel);
	const isDeepseek = selectedModelData?.chefSlug === "deepseek";

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
		<>
			<PromptInput
				globalDrop
				multiple
				onSubmit={handleSubmit}
				className={cn(
					"min-h-40 transition-all duration-200",
					// Sage-style InputGroup container
					"[&>[data-slot=input-group]]:rounded-[28px]",
					"[&>[data-slot=input-group]]:border-[1.5px]",
					"[&>[data-slot=input-group]]:border-[#E0E8E4]",
					"dark:[&>[data-slot=input-group]]:border-white/10",
					"[&>[data-slot=input-group]]:bg-white",
					"dark:[&>[data-slot=input-group]]:bg-[#1C1C1C]",
					"[&>[data-slot=input-group]]:shadow-[0_8px_24px_-12px_rgba(30,45,40,0.08)]",
					"dark:[&>[data-slot=input-group]]:shadow-[0_8px_24px_-12px_rgba(0,0,0,0.3)]",
					"[&>[data-slot=input-group]]:transition-colors",
					"[&>[data-slot=input-group]:focus-within]:border-[#4CA882]",
					"dark:[&>[data-slot=input-group]:focus-within]:border-[#4CA882]",
					// Remove default focus ring
					"[&>[data-slot=input-group]]:has-[[data-slot=input-group-control]:focus-visible]:ring-0",
					className,
				)}
			>
				<PromptInputAttachments className="px-5 pt-4">
					{(attachment) => <PromptInputAttachment data={attachment} />}
				</PromptInputAttachments>
				<PromptInputBody>
					<PromptInputTextarea
						ref={textareaRef}
						disabled={agentReady === false}
						className={cn(
							"font-[family-name:var(--font-dm-sans)]",
							"text-[15px] font-medium leading-relaxed",
							"text-[#1E2D28] dark:text-white",
							"placeholder:text-[#A3B5AD] dark:placeholder:text-white/30",
							"px-5 pt-5 pb-2",
						)}
					/>
				</PromptInputBody>
				<PromptInputFooter className="px-4 pb-4">
					<PromptInputTools className="gap-1.5">
						{isDeepseek ? (
							<Tooltip>
								<TooltipTrigger asChild>
									<span>
										<PromptInputAddAttachmentButton
											disabled
											className={sagePromptToolButtonClass}
										/>
									</span>
								</TooltipTrigger>
								<TooltipContent>
									DeepSeek models do not support attachments.
								</TooltipContent>
							</Tooltip>
						) : (
							<PromptInputAddAttachmentButton
								disabled={agentReady === false}
								className={sagePromptToolButtonClass}
							/>
						)}
						{/* <PromptInputSpeechButton textareaRef={textareaRef} />
						<PromptInputButton>
							<GlobeIcon size={16} />
							<span>Search</span>
						</PromptInputButton> */}
						{readOnlyModel ? (
							<PromptInputButton
								disabled
								className={sagePromptToolButtonClass}
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
									<PromptInputButton className={sagePromptToolButtonClass}>
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
											<span className="truncate text-left text-[#8FA89E] dark:text-white/40">
												Select model
											</span>
										)}
									</PromptInputButton>
								</DialogTrigger>
								<DialogContent
									className="sm:max-w-[480px] rounded-[28px] p-0 gap-0 overflow-hidden"
									showCloseButton={false}
								>
									<div className="flex items-start justify-between px-7 pt-6 pb-4">
										<div>
											<DialogTitle className="font-[family-name:var(--font-jakarta-sans)] text-[20px] font-extrabold text-[#111111] dark:text-white tracking-[-0.02em]">
												Select a model
											</DialogTitle>
											<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#8FA89E] dark:text-muted-foreground font-medium mt-1">
												Choose the model powering this chat
											</p>
										</div>
									</div>

									<div className="px-7 pb-3">
										<SearchBar
											placeholder="Search models..."
											value={modelSearch}
											onChange={setModelSearch}
										/>
									</div>

									<div className="px-4 pb-5 max-h-[55vh] overflow-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
										{!hasModelResults ? (
											<div className="font-[family-name:var(--font-dm-sans)] px-4 py-8 text-center text-[13px] text-[#A3B5AD] dark:text-muted-foreground">
												No models found.
											</div>
										) : (
											Object.entries(groupedModels).map(
												([chefName, chefModels]) => (
													<div key={chefName} className="px-2 pt-2">
														<div className="font-[family-name:var(--font-dm-sans)] px-3 pb-1.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-[#8FA89E] dark:text-muted-foreground">
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
																			"flex w-full items-center gap-3 px-3 py-2.5 rounded-[14px] cursor-pointer transition-colors text-left outline-none",
																			"font-[family-name:var(--font-dm-sans)] text-[14px] font-medium",
																			isActive
																				? "bg-[#F8FAF9] dark:bg-white/5 text-[#1E2D28] dark:text-white"
																				: "text-[#1E2D28] dark:text-white/90 hover:bg-[#F8FAF9] dark:hover:bg-white/5",
																		)}
																	>
																		<ModelSelectorLogo provider={m.chefSlug} />
																		<span className="flex-1 truncate">
																			{m.name}
																		</span>
																		{isActive && (
																			<CheckIcon
																				className="ml-auto size-4 shrink-0 text-[#4CA882]"
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
				"flex items-center justify-center rounded-full w-10 h-10 transition-all",
				isDisabled
					? "bg-[#EDF4F0] dark:bg-white/5 text-[#A3B5AD] dark:text-white/30 cursor-not-allowed"
					: "bg-[#4CA882] text-white hover:bg-[#3F8F70] hover:scale-105 cursor-pointer shadow-[0_4px_12px_-4px_rgba(76,168,130,0.4)]",
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
				"font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold",
				"bg-[#4CA882] text-white hover:bg-[#3F8F70]",
				"shadow-[0_4px_12px_-4px_rgba(76,168,130,0.4)]",
			)}
		>
			<PlugIcon size={16} />
			<span>Connect</span>
		</button>
	);
};

export default ChatPromptInput;

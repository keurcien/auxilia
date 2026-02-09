"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { v4 as uuidv4 } from "uuid";
import { type PromptInputMessage } from "@/components/ai-elements/prompt-input";
import ChatPromptInput from "./components/prompt-input";
import { useThreadsStore } from "@/stores/threads-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useModelsStore } from "@/stores/models-store";
import { api } from "@/lib/api/client";
import { Agent } from "@/types/agents";
import { NewThreadDialog } from "@/components/layout/app-sidebar/new-thread-dialog";
import { getDefaultModel } from "@/lib/utils/get-default-model";

const StarterChatPage = () => {
	const params = useParams();
	const router = useRouter();
	const agentId = params.id as string;
	const [isCreating, setIsCreating] = useState(false);
	const [selectedModel, setSelectedModel] = useState<string | undefined>(
		undefined,
	);
	const addThread = useThreadsStore((state) => state.addThread);
	const setPendingMessage = usePendingMessageStore(
		(state) => state.setPendingMessage,
	);
	const models = useModelsStore((state) => state.models);
	const fetchModels = useModelsStore((state) => state.fetchModels);
	const [agent, setAgent] = useState<Agent | null>(null);
	const [isAgentDialogOpen, setIsAgentDialogOpen] = useState(false);

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

		try {
			// Generate thread ID on frontend
			const threadId = uuidv4();

			// Store the pending message (with files) to be consumed by the thread page
			setPendingMessage(threadId, message);

			// Extract text for display purposes (thread list preview)
			const textContent = "text" in message ? message.text : undefined;

			const response = await api.post("/threads", {
				id: threadId,
				agentId: agentId,
				modelId,
				firstMessageContent: textContent,
			});

			const thread = {
				...response.data,
				agentName: agent?.name ?? null,
				agentEmoji: agent?.emoji ?? null,
			};

			addThread(thread);

			router.push(`/agents/${agentId}/chat/${threadId}`);
		} catch (error) {
			console.error("Error creating thread:", error);
			setIsCreating(false);
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
		if (selectedModel) {
			return;
		}

		const defaultModel = getDefaultModel(models);
		if (defaultModel) {
			setSelectedModel(defaultModel);
		}
	}, [models, selectedModel]);

	useEffect(() => {
		const fetchAgent = async () => {
			const response = await api.get(`/agents/${agentId}`);
			const agent = response.data;
			setAgent(agent);
		};
		fetchAgent();
	}, [agentId]);

	return (
		<div className="container mx-auto h-full flex flex-col items-center justify-center max-w-4xl px-6">
			<div className="w-full max-w-3xl space-y-8">
				<div className="text-center space-y-4">
					<button
						onClick={() => setIsAgentDialogOpen(true)}
						className="flex items-center justify-center gap-2 mx-auto hover:opacity-80 transition-opacity cursor-pointer"
					>
						<div className="shrink-0 w-12 h-12 rounded-2xl bg-muted text-2xl flex items-center justify-center">
							{agent?.emoji || "🤖"}
						</div>
						<h1 className="text-4xl font-bold">{agent?.name}</h1>
					</button>
					<p className="text-lg text-muted-foreground">
						Ask me anything to begin
					</p>
				</div>

				<div className="w-full">
					<ChatPromptInput
						onSubmit={handleSubmit}
						status={isCreating ? "streaming" : "ready"}
						className="w-full"
						selectedModel={selectedModel}
						onModelChange={setSelectedModel}
					/>
				</div>
			</div>

			<NewThreadDialog
				open={isAgentDialogOpen}
				onOpenChange={setIsAgentDialogOpen}
			/>
		</div>
	);
};

export default StarterChatPage;

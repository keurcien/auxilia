import { create } from "zustand";

interface ChatHeaderState {
	agentName: string | null;
	agentEmoji: string | null;
	modelId: string | null;
	setCurrentChat: (data: {
		agentName: string | null;
		agentEmoji: string | null;
		modelId: string | null;
	}) => void;
	clearCurrentChat: () => void;
}

export const useChatHeaderStore = create<ChatHeaderState>((set) => ({
	agentName: null,
	agentEmoji: null,
	modelId: null,
	setCurrentChat: (data) => set(data),
	clearCurrentChat: () =>
		set({ agentName: null, agentEmoji: null, modelId: null }),
}));

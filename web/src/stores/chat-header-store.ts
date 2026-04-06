import { create } from "zustand";

interface ChatHeaderState {
	agentName: string | null;
	agentEmoji: string | null;
	agentColor: string | null;
	modelId: string | null;
	setCurrentChat: (data: {
		agentName: string | null;
		agentEmoji: string | null;
		agentColor?: string | null;
		modelId: string | null;
	}) => void;
	clearCurrentChat: () => void;
}

export const useChatHeaderStore = create<ChatHeaderState>((set) => ({
	agentName: null,
	agentEmoji: null,
	agentColor: null,
	modelId: null,
	setCurrentChat: (data) => set({ agentColor: null, ...data }),
	clearCurrentChat: () =>
		set({ agentName: null, agentEmoji: null, agentColor: null, modelId: null }),
}));

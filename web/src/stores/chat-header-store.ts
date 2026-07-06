import { create } from "zustand";

interface ChatHeaderState {
  agentName: string | null;
  agentEmoji: string | null;
  agentColor: string | null;
  modelId: string | null;
  /** Set for trigger-fired threads: the trigger's id, name and firing time. */
  triggerId: string | null;
  triggerName: string | null;
  triggerRunAt: string | null;
  setCurrentChat: (data: {
    agentName: string | null;
    agentEmoji: string | null;
    agentColor?: string | null;
    modelId: string | null;
    triggerId?: string | null;
    triggerName?: string | null;
    triggerRunAt?: string | null;
  }) => void;
  clearCurrentChat: () => void;
}

export const useChatHeaderStore = create<ChatHeaderState>((set) => ({
  agentName: null,
  agentEmoji: null,
  agentColor: null,
  modelId: null,
  triggerId: null,
  triggerName: null,
  triggerRunAt: null,
  setCurrentChat: (data) => {
    set({
      agentColor: null,
      triggerId: null,
      triggerName: null,
      triggerRunAt: null,
      ...data,
    });
  },
  clearCurrentChat: () => {
    set({
      agentName: null,
      agentEmoji: null,
      agentColor: null,
      modelId: null,
      triggerId: null,
      triggerName: null,
      triggerRunAt: null,
    });
  },
}));

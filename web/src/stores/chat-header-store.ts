import { create } from "zustand";
import type { ThreadCost } from "@/lib/api/resources/thread-costs";

/** The project a conversation lives in (or will be created in). */
export interface ChatHeaderProject {
  id: string;
  name: string;
  emoji: string | null;
  /** Folder path inside the project, e.g. "Specs / Drafts". */
  folderPath: string | null;
  href: string;
}

interface ChatHeaderState {
  /** The thread's agent — the header links to its page when set. */
  agentId: string | null;
  agentName: string | null;
  agentEmoji: string | null;
  agentColor: string | null;
  agentImageRevision: string | null;
  modelId: string | null;
  /** Set for trigger-fired threads: the trigger's id, name and firing time. */
  triggerId: string | null;
  triggerName: string | null;
  triggerRunAt: string | null;
  /** The open thread's cost estimate, shown beside its model. */
  cost: ThreadCost | null;
  setCost: (cost: ThreadCost | null) => void;
  project: ChatHeaderProject | null;
  setProject: (project: ChatHeaderProject | null) => void;
  /** Right-hand slot in the header; chat pages portal actions into it. */
  actionsEl: HTMLElement | null;
  setActionsEl: (element: HTMLElement | null) => void;
  /** Left-hand slot for state controls on an existing conversation. */
  leadingActionsEl: HTMLElement | null;
  setLeadingActionsEl: (element: HTMLElement | null) => void;
  setCurrentChat: (data: {
    agentId?: string | null;
    agentName: string | null;
    agentEmoji: string | null;
    agentColor?: string | null;
    agentImageRevision?: string | null;
    modelId: string | null;
    triggerId?: string | null;
    triggerName?: string | null;
    triggerRunAt?: string | null;
  }) => void;
  clearCurrentChat: () => void;
}

export const useChatHeaderStore = create<ChatHeaderState>((set) => ({
  agentId: null,
  agentName: null,
  agentEmoji: null,
  agentColor: null,
  agentImageRevision: null,
  modelId: null,
  triggerId: null,
  triggerName: null,
  triggerRunAt: null,
  cost: null,
  setCost: (cost) => {
    set({ cost });
  },
  project: null,
  setProject: (project) => {
    set({ project });
  },
  actionsEl: null,
  setActionsEl: (actionsEl) => {
    set({ actionsEl });
  },
  leadingActionsEl: null,
  setLeadingActionsEl: (leadingActionsEl) => {
    set({ leadingActionsEl });
  },
  setCurrentChat: (data) => {
    set({
      agentId: null,
      agentColor: null,
      agentImageRevision: null,
      triggerId: null,
      triggerName: null,
      triggerRunAt: null,
      ...data,
    });
  },
  clearCurrentChat: () => {
    set({
      agentId: null,
      agentName: null,
      agentEmoji: null,
      agentColor: null,
      agentImageRevision: null,
      modelId: null,
      triggerId: null,
      triggerName: null,
      triggerRunAt: null,
      cost: null,
      project: null,
    });
  },
}));

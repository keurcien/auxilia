import { create } from "zustand";

import type { WorkspaceInvalidation } from "@/types/workspace-events";

export type WorkspaceEventConnection =
  | "idle"
  | "connecting"
  | "connected"
  | "disconnected";

interface WorkspaceEventsState {
  connection: WorkspaceEventConnection;
  syncVersion: number;
  agentsVersion: number;
  triggersVersion: number;
  mcpServersVersion: number;
  skillsVersion: number;
  threadsVersion: number;
  projectsVersion: number;
  runsVersion: number;
  triggerHistoryVersion: number;
  queueVersions: Record<string, number>;
  setConnection: (connection: WorkspaceEventConnection) => void;
  sync: () => void;
  invalidate: (event: WorkspaceInvalidation) => void;
  reset: () => void;
}

const initialVersions = {
  syncVersion: 0,
  agentsVersion: 0,
  triggersVersion: 0,
  mcpServersVersion: 0,
  skillsVersion: 0,
  threadsVersion: 0,
  projectsVersion: 0,
  runsVersion: 0,
  triggerHistoryVersion: 0,
  queueVersions: {},
};

export const useWorkspaceEventsStore = create<WorkspaceEventsState>((set) => ({
  connection: "idle",
  ...initialVersions,
  setConnection: (connection) => {
    set({ connection });
  },
  sync: () => {
    set((state) => ({
      syncVersion: state.syncVersion + 1,
      agentsVersion: state.agentsVersion + 1,
      triggersVersion: state.triggersVersion + 1,
      mcpServersVersion: state.mcpServersVersion + 1,
      skillsVersion: state.skillsVersion + 1,
      threadsVersion: state.threadsVersion + 1,
      projectsVersion: state.projectsVersion + 1,
      runsVersion: state.runsVersion + 1,
      triggerHistoryVersion: state.triggerHistoryVersion + 1,
    }));
  },
  invalidate: (event) => {
    switch (event.kind) {
      case "agents":
        set((state) => ({ agentsVersion: state.agentsVersion + 1 }));
        break;
      case "triggers":
        set((state) => ({
          triggersVersion: state.triggersVersion + 1,
          projectsVersion: state.projectsVersion + 1,
        }));
        break;
      case "mcp_servers":
        set((state) => ({
          mcpServersVersion: state.mcpServersVersion + 1,
        }));
        break;
      case "skills":
        set((state) => ({ skillsVersion: state.skillsVersion + 1 }));
        break;
      case "threads":
        set((state) => ({
          threadsVersion: state.threadsVersion + 1,
          projectsVersion: state.projectsVersion + 1,
        }));
        break;
      case "projects":
        set((state) => ({ projectsVersion: state.projectsVersion + 1 }));
        break;
      case "runs":
        set((state) => ({ runsVersion: state.runsVersion + 1 }));
        break;
      case "trigger_history":
        set((state) => ({
          triggerHistoryVersion: state.triggerHistoryVersion + 1,
        }));
        break;
      case "prompt_queue": {
        const threadId = event.threadId;
        if (threadId === undefined) break;
        set((state) => ({
          queueVersions: {
            ...state.queueVersions,
            [threadId]: (state.queueVersions[threadId] ?? 0) + 1,
          },
        }));
        break;
      }
    }
  },
  reset: () => {
    set({ connection: "idle", ...initialVersions });
  },
}));

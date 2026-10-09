import { advanceWorkspaceGeneration } from "@/lib/workspace-generation";
import { useActiveRunsStore } from "@/stores/active-runs-store";
import { useAgentsStore } from "@/stores/agents-store";
import { useChatHeaderStore } from "@/stores/chat-header-store";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import { useModelsStore } from "@/stores/models-store";
import { usePendingMessageStore } from "@/stores/pending-message-store";
import { useSkillsStore } from "@/stores/skills-store";
import { useThreadsStore } from "@/stores/threads-store";
import { useTriggerRunsStore } from "@/stores/trigger-runs-store";
import { useTriggersStore } from "@/stores/triggers-store";

export function resetWorkspaceStores(): void {
	advanceWorkspaceGeneration();
	useAgentsStore.setState({ agents: [], isInitialized: false });
	useThreadsStore.setState({ threads: [], total: 0, isLoadingMore: false });
	useMcpServersStore.setState({ mcpServers: [], isInitialized: false });
	useTriggersStore.setState({ triggers: [], isInitialized: false });
	useTriggerRunsStore.setState({ runsByTrigger: {} });
	useSkillsStore.setState({
		skills: [],
		isInitialized: false,
		sources: [],
		sourcesInitialized: false,
	});
	useModelsStore.setState({ models: [], isInitialized: false });
	useActiveRunsStore.setState((state) => ({
		confirmedThreadIds: [],
		optimisticMarkedAt: {},
		pollEpoch: state.pollEpoch + 1,
		lastPolledAt: null,
		pendingSince: null,
		pollSeq: state.pollSeq + 1,
	}));
	usePendingMessageStore.setState({ pendingMessages: new Map() });
	useChatHeaderStore.getState().clearCurrentChat();
}

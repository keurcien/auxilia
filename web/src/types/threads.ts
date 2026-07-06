export type ThreadSource = "web" | "slack" | "api" | "trigger";

export interface Thread {
	id: string;
	agentId: string;
	userId: string;
	firstMessageContent: string;
	agentName: string | null;
	agentEmoji: string | null;
	agentColor: string | null;
	agentArchived: boolean;
	source: ThreadSource;
	triggerId?: string | null;
	createdAt: string;
}

export interface AgentThread extends Thread {
	userEmail: string | null;
	userName: string | null;
}

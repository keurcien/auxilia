export type ThreadSource = "web" | "slack" | "api";

export type ViewerRole = "admin";

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
	createdAt: string;
}

export interface AgentThread extends Thread {
	userEmail: string | null;
	userName: string | null;
}

export interface Thread {
	id: string;
	agentId: string;
	firstMessageContent: string;
	agentName: string | null;
	agentEmoji: string | null;
	agentArchived: boolean;
	createdAt: string;
}

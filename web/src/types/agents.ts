import { MCPAuthType, MCPCredentialScope, MCPServer } from "./mcp-servers";
import { SandboxProviderType } from "./sandboxes";
import { AgentSkill } from "./skills";
import type { ResourceVisibility } from "./visibility";

export type ToolStatus = "always_allow" | "needs_approval" | "disabled";
export type ToolDiscoveryMode = "disabled" | "lazy" | "local";
/** A Slack connection's discovery policy: an agent mode applied to the whole
 * graph, or `all_capabilities` — eager schemas plus every resource the agent
 * disables by default. */
export type SlackToolDiscoveryMode = ToolDiscoveryMode | "all_capabilities";

interface AgentMCPServer extends MCPServer {
	mcpServerId: string;
	/** Detail responses only; defaults to true for older/list projections. */
	enabledByDefault?: boolean;
	/** Absent on list responses; the detail response carries the full map
	 * (null = never synced). */
	tools?: Record<string, ToolStatus> | null;
}

/** One agent↔sandbox binding, flattened with the sandbox's display fields. */
export interface AgentSandbox {
	sandboxId: string;
	enabledByDefault?: boolean;
	tools: Record<string, ToolStatus> | null;
	name: string;
	provider: SandboxProviderType;
	url: string;
	imageRevision: string | null;
}

/** An agent still bound to a workspace resource (sandbox, MCP server) —
 * shown in the delete-guard dialog. */
export interface BoundAgent {
	id: string;
	name: string;
	emoji: string | null;
	color: string | null;
	imageRevision?: string | null;
}

export type AgentPermission = "owner" | "admin" | "editor" | "member";

/** Can this viewer configure the agent (edit instructions, MCP tools)? */
export const canConfigureAgent = (
	permission?: AgentPermission | null,
): boolean =>
	permission === "owner" || permission === "admin" || permission === "editor";

/** Bot credentials remain server-side; this is the safe agent settings projection. */
export interface AgentSlackBotSettings {
	id: string | null;
	workspaceEnabled: boolean;
	enabled: boolean;
	requireMentionInThreads: boolean;
	showToolCallouts: boolean;
	showThinkingMessage: boolean;
	showAuxiliaLink: boolean;
	toolDiscoveryMode: SlackToolDiscoveryMode;
	isConfigured: boolean;
	botTokenLast4: string | null;
	hasSigningSecret: boolean;
	slackTeamId: string | null;
	slackTeamName: string | null;
	botUserId: string | null;
	botName: string | null;
	eventsUrl: string;
	interactionsUrl: string;
	manifest: Record<string, unknown>;
}

export interface AgentSlackBotSettingsUpdate {
	enabled: boolean;
	requireMentionInThreads: boolean;
	showToolCallouts: boolean;
	showThinkingMessage: boolean;
	showAuxiliaLink: boolean;
	toolDiscoveryMode: SlackToolDiscoveryMode;
	botToken?: string;
	signingSecret?: string;
}

export type TelegramToolDiscoveryMode = ToolDiscoveryMode | "all_capabilities";

export interface AgentTelegramBotSettings {
	id: string | null;
	agentId: string;
	workspaceEnabled: boolean;
	enabled: boolean;
	requireMentionInGroups: boolean;
	showToolCallouts: boolean;
	showAuxiliaLink: boolean;
	toolDiscoveryMode: TelegramToolDiscoveryMode;
	isConfigured: boolean;
	botTokenLast4: string | null;
	botId: string | null;
	botUsername: string | null;
	botName: string | null;
	webhookUrl: string;
	deepLinkUrl: string | null;
}

export interface AgentTelegramBotSettingsUpdate {
	enabled: boolean;
	requireMentionInGroups: boolean;
	showToolCallouts: boolean;
	showAuxiliaLink: boolean;
	toolDiscoveryMode: TelegramToolDiscoveryMode;
	botToken?: string;
}

export type WhatsAppToolDiscoveryMode = ToolDiscoveryMode | "all_capabilities";

/** Meta credentials stay server-side; this is the safe WhatsApp projection. */
export interface AgentWhatsAppSettings {
	id: string | null;
	agentId: string;
	workspaceEnabled: boolean;
	enabled: boolean;
	showTypingIndicator: boolean;
	showToolCallouts: boolean;
	showAuxiliaLink: boolean;
	toolDiscoveryMode: WhatsAppToolDiscoveryMode;
	isConfigured: boolean;
	accessTokenLast4: string | null;
	hasAppSecret: boolean;
	businessAccountId: string | null;
	phoneNumberId: string | null;
	displayPhoneNumber: string | null;
	verifiedName: string | null;
	webhookUrl: string;
	verifyToken: string | null;
	deepLinkUrl: string | null;
}

export interface AgentWhatsAppSettingsUpdate {
	enabled: boolean;
	showTypingIndicator: boolean;
	showToolCallouts: boolean;
	showAuxiliaLink: boolean;
	toolDiscoveryMode: WhatsAppToolDiscoveryMode;
	accessToken?: string;
	appSecret?: string;
	businessAccountId?: string;
	phoneNumberId?: string;
}

export interface SubagentInfo {
	id: string;
	name: string;
	emoji?: string | null;
	color?: string | null;
	imageRevision?: string | null;
	description?: string | null;
	enabledByDefault?: boolean;
}

export interface AgentOwner {
	id: string;
	name?: string | null;
	email?: string | null;
	pictureUrl?: string | null;
	imageRevision?: string | null;
}

export interface Agent {
	id: string;
	name: string;
	/** Absent on list responses (GET /agents returns slim rows); present on
	 * detail responses (GET /agents/{id}) and save results. */
	instructions?: string;
	ownerId: string;
	emoji?: string | null;
	color?: string | null;
	imageRevision?: string | null;
	description?: string | null;
	isArchived: boolean;
	isDefault: boolean;
	mcpServers: AgentMCPServer[];
	/** Absent on list responses, like `instructions`; present on detail responses. */
	sandboxes?: AgentSandbox[];
	/** Skills enabled on the agent. Detail responses only, like sandboxes. */
	skills?: AgentSkill[];
	subagents: SubagentInfo[];
	group?: string | null;
	visibility: ResourceVisibility;
	webSearchEnabled?: boolean;
	toolDiscoveryMode?: ToolDiscoveryMode;
	/** Detail responses only. Null inherits the workspace default model. */
	defaultModelId?: string | null;
	defaultReasoningEffort?: string | null;
	teamIds: string[];
	owner?: AgentOwner | null;
	isSubagent: boolean;
	currentUserPermission?: AgentPermission | null;
}

export interface AgentResourceMCPServer {
	id: string;
	name: string;
	iconUrl: string | null;
	imageRevision: string | null;
	description: string | null;
	authType: MCPAuthType;
	credentialScope: MCPCredentialScope;
	personalHeaderNames: string[];
	toolNames: string[];
	configured: boolean;
	enabledByDefault: boolean;
}

export interface AgentResourceSandbox {
	id: string;
	name: string;
	description: string | null;
	provider: SandboxProviderType;
	imageRevision: string | null;
	enabledByDefault: boolean;
}

export interface AgentResources {
	mcpServers: AgentResourceMCPServer[];
	skills: AgentSkill[];
	sandboxes: AgentResourceSandbox[];
	subagents: SubagentInfo[];
}

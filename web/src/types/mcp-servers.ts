export type MCPAuthType = "none" | "api_key" | "oauth2";

export interface MCPServer {
	id: string;
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	description?: string;
	createdAt: string;
	updatedAt: string;
}

export interface MCPServerCreate {
	name: string;
	url: string;
	authType: MCPAuthType;
	iconUrl?: string;
	description?: string;
	apiKey?: string;
}

export interface MCPServerUpdate {
	name?: string;
	url?: string;
	authType?: MCPAuthType;
	iconUrl?: string;
	description?: string;
}

export interface OfficialMCPServer extends MCPServer {
	isInstalled: boolean;
}

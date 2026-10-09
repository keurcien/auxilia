export interface WorkspaceObservabilitySettings {
	enabled: boolean;
	isConfigured: boolean;
	baseUrl: string;
	timeoutSeconds: number;
	publicKeyLast4: string | null;
	publicKeyLength: number | null;
	hasSecretKey: boolean;
}

export interface WorkspaceObservabilityUpdate {
	enabled: boolean;
	baseUrl: string;
	timeoutSeconds: number;
	publicKey?: string;
	secretKey?: string;
}

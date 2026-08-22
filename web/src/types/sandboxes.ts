export type SandboxProviderType = "opensandbox" | "cloudrun" | "daytona";

export interface Sandbox {
	id: string;
	name: string;
	description: string | null;
	provider: SandboxProviderType;
	url: string;
	/** Provider-specific config (camelCase — the axios client converts). */
	config: Record<string, unknown>;
	hasSecret: boolean;
	createdAt: string;
	updatedAt: string;
}

export interface SandboxSecretHint {
	isSet: boolean;
	last4: string | null;
	length: number | null;
}

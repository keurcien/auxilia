export interface SlackNotificationSettings {
	enabled: boolean;
	isConfigured: boolean;
	botTokenLast4: string | null;
	botTokenLength: number | null;
	hasSigningSecret: boolean;
	eventsUrl: string;
	interactionsUrl: string;
}

export interface SlackNotificationSettingsUpdate {
	enabled: boolean;
	botToken?: string;
	signingSecret?: string;
}

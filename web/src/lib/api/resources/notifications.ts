import { api } from "@/lib/api/client";
import type {
	SlackNotificationSettings,
	SlackNotificationSettingsUpdate,
} from "@/types/notifications";

export async function getSlackSettings(): Promise<SlackNotificationSettings> {
	const response =
		await api.get<SlackNotificationSettings>("/notifications/slack");
	return response.data;
}

export async function updateSlackSettings(
	update: SlackNotificationSettingsUpdate,
): Promise<SlackNotificationSettings> {
	const response = await api.put<SlackNotificationSettings>(
		"/notifications/slack",
		update,
	);
	return response.data;
}

export async function deleteSlackSettings(): Promise<SlackNotificationSettings> {
	const response =
		await api.delete<SlackNotificationSettings>("/notifications/slack");
	return response.data;
}

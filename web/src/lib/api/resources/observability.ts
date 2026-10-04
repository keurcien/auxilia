import { api } from "@/lib/api/client";
import type {
	WorkspaceObservabilitySettings,
	WorkspaceObservabilityUpdate,
} from "@/types/observability";

export async function getObservabilitySettings(): Promise<WorkspaceObservabilitySettings> {
	const response =
		await api.get<WorkspaceObservabilitySettings>("/observability/");
	return response.data;
}

export async function updateObservabilitySettings(
	update: WorkspaceObservabilityUpdate,
): Promise<WorkspaceObservabilitySettings> {
	const response = await api.put<WorkspaceObservabilitySettings>(
		"/observability/",
		update,
	);
	return response.data;
}

export async function deleteObservabilitySettings(): Promise<WorkspaceObservabilitySettings> {
	const response =
		await api.delete<WorkspaceObservabilitySettings>("/observability/");
	return response.data;
}

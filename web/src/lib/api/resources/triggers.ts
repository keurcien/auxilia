/**
 * Trigger resource — `/triggers`: scheduled agent runs, their past firings,
 * and the schedule preview.
 *
 * Plain functions over the axios client: routes, params and response types
 * live here and nowhere else. No React, no stores, no toasts; failures reject
 * with `ApiError`. Cache updates belong to the store that calls these.
 */
import { api } from "@/lib/api/client";
import type {
	SchedulePreview,
	Trigger,
	TriggerCreate,
	TriggerRun,
	TriggerThread,
	TriggerUpdate,
} from "@/types/triggers";

/** Every trigger visible to the caller. */
export async function listTriggers(): Promise<Trigger[]> {
	const response = await api.get<Trigger[]>("/triggers");
	return response.data;
}

/**
 * One trigger. `cookie` forwards the browser session when called from a
 * server component (the axios client has no cookie jar there).
 */
export async function getTrigger(
	triggerId: string,
	options: { cookie?: string } = {},
): Promise<Trigger> {
	const response = await api.get<Trigger>(`/triggers/${triggerId}`, {
		headers: options.cookie ? { Cookie: options.cookie } : undefined,
	});
	return response.data;
}

export async function createTrigger(payload: TriggerCreate): Promise<Trigger> {
	const response = await api.post<Trigger>("/triggers", payload);
	return response.data;
}

export async function updateTrigger(
	triggerId: string,
	payload: TriggerUpdate,
): Promise<Trigger> {
	const response = await api.patch<Trigger>(`/triggers/${triggerId}`, payload);
	return response.data;
}

export async function deleteTrigger(triggerId: string): Promise<void> {
	await api.delete(`/triggers/${triggerId}`);
}

/** Fire the trigger now; the run works in the background on a new thread. */
export async function runTrigger(triggerId: string): Promise<TriggerRun> {
	const response = await api.post<TriggerRun>(`/triggers/${triggerId}/run`);
	return response.data;
}

/** Past firings of one trigger — each is a thread, newest first. */
export async function listTriggerThreads(
	triggerId: string,
): Promise<TriggerThread[]> {
	const response = await api.get<TriggerThread[]>(
		`/triggers/${triggerId}/threads`,
	);
	return response.data;
}

/**
 * Upcoming firings for a cron/timezone pair, computed by the backend. A 400
 * doubles as schedule validation.
 */
export async function previewSchedule(
	cronExpression: string,
	timezone: string,
	count = 3,
): Promise<SchedulePreview> {
	const response = await api.get<SchedulePreview>(
		"/triggers/schedule/preview",
		{ params: { cronExpression, timezone, count } },
	);
	return response.data;
}

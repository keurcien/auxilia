import { create } from "zustand";
import {
	Trigger,
	TriggerCreate,
	TriggerRun,
	TriggerUpdate,
} from "@/types/triggers";
import { api } from "@/lib/api/client";

interface TriggersState {
	triggers: Trigger[];
	isInitialized: boolean;
	fetchTriggers: () => Promise<void>;
	createTrigger: (payload: TriggerCreate) => Promise<Trigger>;
	updateTrigger: (id: string, payload: TriggerUpdate) => Promise<Trigger>;
	deleteTrigger: (id: string) => Promise<void>;
	runTrigger: (id: string) => Promise<TriggerRun>;
	upsertTrigger: (trigger: Trigger) => void;
}

export const useTriggersStore = create<TriggersState>((set, get) => ({
	triggers: [],
	isInitialized: false,
	fetchTriggers: async () => {
		if (get().isInitialized) {
			return;
		}

		try {
			const response = await api.get("/triggers");
			set({ triggers: response.data, isInitialized: true });
		} catch (error) {
			console.error("Error fetching triggers:", error);
			set({ isInitialized: true });
			throw error;
		}
	},
	createTrigger: async (payload) => {
		const response = await api.post("/triggers", payload);
		const created: Trigger = response.data;
		set((state) => ({ triggers: [created, ...state.triggers] }));
		return created;
	},
	updateTrigger: async (id, payload) => {
		const response = await api.patch(`/triggers/${id}`, payload);
		const updated: Trigger = response.data;
		set((state) => ({
			triggers: state.triggers.map((trigger) =>
				trigger.id === id ? updated : trigger,
			),
		}));
		return updated;
	},
	deleteTrigger: async (id) => {
		await api.delete(`/triggers/${id}`);
		set((state) => ({
			triggers: state.triggers.filter((trigger) => trigger.id !== id),
		}));
	},
	runTrigger: async (id) => {
		const response = await api.post(`/triggers/${id}/run`);
		return response.data as TriggerRun;
	},
	upsertTrigger: (trigger) => {
		set((state) => {
			const exists = state.triggers.some((t) => t.id === trigger.id);
			return {
				triggers: exists
					? state.triggers.map((t) => (t.id === trigger.id ? trigger : t))
					: [trigger, ...state.triggers],
			};
		});
	},
}));

import { create } from "zustand";
import {
	Trigger,
	TriggerCreate,
	TriggerRun,
	TriggerUpdate,
} from "@/types/triggers";
import { createOnce } from "@/lib/api/once";
import * as triggersApi from "@/lib/api/resources/triggers";

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

export const useTriggersStore = create<TriggersState>((set, get) => {
	// One request even when several components mount before the first load
	// resolves (sidebar count + triggers page).
	const load = createOnce(async () => {
		try {
			const triggers = await triggersApi.listTriggers();
			set({ triggers, isInitialized: true });
		} catch (error) {
			console.error("Error fetching triggers:", error);
			set({ isInitialized: true });
			throw error;
		}
	});

	return {
		triggers: [],
		isInitialized: false,
		fetchTriggers: async () => {
			if (get().isInitialized) {
				return;
			}
			await load.run();
		},
		createTrigger: async (payload) => {
			const created = await triggersApi.createTrigger(payload);
			set((state) => ({ triggers: [created, ...state.triggers] }));
			return created;
		},
		updateTrigger: async (id, payload) => {
			const updated = await triggersApi.updateTrigger(id, payload);
			set((state) => ({
				triggers: state.triggers.map((trigger) =>
					trigger.id === id ? updated : trigger,
				),
			}));
			return updated;
		},
		deleteTrigger: async (id) => {
			await triggersApi.deleteTrigger(id);
			set((state) => ({
				triggers: state.triggers.filter((trigger) => trigger.id !== id),
			}));
		},
		runTrigger: (id) => triggersApi.runTrigger(id),
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
	};
});

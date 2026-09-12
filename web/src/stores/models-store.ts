import { create } from "zustand";
import * as modelsApi from "@/lib/api/resources/models";
import { Model } from "@/types/models";

interface ModelsState {
	models: Model[];
	isInitialized: boolean;
	fetchModels: () => Promise<void>;
	refreshModels: () => Promise<void>;
}

export const useModelsStore = create<ModelsState>((set, get) => ({
	models: [],
	isInitialized: false,
	fetchModels: async () => {
		if (get().isInitialized) {
			return;
		}
		await get().refreshModels();
	},
	// Force refetch — used after admins change the enabled set so every open
	// model selector reflects it without a page reload.
	refreshModels: async () => {
		try {
			const models = await modelsApi.listModels();
			set({ models, isInitialized: true });
		} catch (error) {
			console.error("Error fetching models:", error);
			// Not initialized on failure — the next fetchModels() retries
			// instead of pinning every picker to an empty catalog.
			throw error;
		}
	},
}));

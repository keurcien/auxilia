import { create } from "zustand";
import { createOnce } from "@/lib/api/once";
import * as appearanceApi from "@/lib/api/resources/appearance";
import type { InstanceAppearance } from "@/types/appearance";

interface AppearanceState {
	appearance: InstanceAppearance;
	isInitialized: boolean;
	fetchAppearance: () => Promise<void>;
	setAppearance: (appearance: InstanceAppearance) => void;
}

const DEFAULT_APPEARANCE: InstanceAppearance = {
	appName: "auxilia",
	logoRevision: null,
};

export const useAppearanceStore = create<AppearanceState>((set, get) => {
	const load = createOnce(async () => {
		try {
			const appearance = await appearanceApi.getAppearance();
			set({ appearance, isInitialized: true });
		} catch (error) {
			console.error("Error fetching instance appearance:", error);
			set({ isInitialized: false });
		}
	});

	return {
		appearance: DEFAULT_APPEARANCE,
		isInitialized: false,
		fetchAppearance: async () => {
			if (get().isInitialized) return;
			await load.run();
		},
		setAppearance: (appearance) => {
			set({ appearance, isInitialized: true });
		},
	};
});

import { create } from "zustand";
import * as usageApi from "@/lib/api/resources/usage";
import {
	getWorkspaceGeneration,
	isCurrentWorkspaceGeneration,
} from "@/lib/workspace-generation";
import type {
	UsageDimension,
	UsageSummariesResponse,
	UsageSummaryParams,
	UsageSummaryResponse,
} from "@/types/usage";

/** Lists ask again at most this often; usage moves with every model call. */
const STALE_AFTER_MS = 60_000;

export type UsageEntityDimension = "agent" | "project" | "trigger" | "user";

const DETAIL_PARAM: Record<UsageEntityDimension, keyof UsageSummaryParams> = {
	agent: "agentId",
	project: "projectId",
	trigger: "triggerId",
	user: "userId",
};

interface Entry<T> {
	data: T | null;
	loadedAt: number;
	loading: boolean;
}

interface UsageSummariesState {
	/** One batched `/usage/summaries` response per entity dimension. */
	byDimension: Partial<Record<UsageDimension, Entry<UsageSummariesResponse>>>;
	/** One entity's `/usage/summary`, with its vendor and model split, by `dimension:id`. */
	details: Record<string, Entry<UsageSummaryResponse>>;
	ensure: (dimension: UsageDimension) => void;
	ensureDetail: (dimension: UsageEntityDimension, id: string) => void;
	/** Drop cached summaries, e.g. after the display currency changed. */
	invalidate: () => void;
}

export function detailKey(dimension: UsageEntityDimension, id: string): string {
	return `${dimension}:${id}`;
}

function isFresh<T>(entry: Entry<T> | undefined): boolean {
	return Boolean(
		entry && (entry.loading || Date.now() - entry.loadedAt < STALE_AFTER_MS),
	);
}

export const useUsageSummariesStore = create<UsageSummariesState>(
	(set, get) => ({
		byDimension: {},
		details: {},
		invalidate: () => {
			set({ byDimension: {}, details: {} });
		},
		ensure: (dimension) => {
			const entry = get().byDimension[dimension];
			if (isFresh(entry)) return;
			const generation = getWorkspaceGeneration();
			const settle = (data: UsageSummariesResponse | null) => {
				if (!isCurrentWorkspaceGeneration(generation)) return;
				set((state) => ({
					byDimension: {
						...state.byDimension,
						[dimension]: { data, loadedAt: Date.now(), loading: false },
					},
				}));
			};
			set((state) => ({
				byDimension: {
					...state.byDimension,
					[dimension]: {
						data: entry?.data ?? null,
						loadedAt: entry?.loadedAt ?? 0,
						loading: true,
					},
				},
			}));
			usageApi
				.getUsageSummaries(dimension)
				.then(settle)
				.catch((error: unknown) => {
					console.error("Error fetching usage summaries:", error);
					settle(entry?.data ?? null);
				});
		},
		ensureDetail: (dimension, id) => {
			const key = detailKey(dimension, id);
			const entry = get().details[key];
			if (isFresh(entry)) return;
			const generation = getWorkspaceGeneration();
			const settle = (data: UsageSummaryResponse | null) => {
				if (!isCurrentWorkspaceGeneration(generation)) return;
				set((state) => ({
					details: {
						...state.details,
						[key]: { data, loadedAt: Date.now(), loading: false },
					},
				}));
			};
			set((state) => ({
				details: {
					...state.details,
					[key]: {
						data: entry?.data ?? null,
						loadedAt: entry?.loadedAt ?? 0,
						loading: true,
					},
				},
			}));
			usageApi
				.getUsageSummary({ [DETAIL_PARAM[dimension]]: id })
				.then(settle)
				.catch((error: unknown) => {
					console.error("Error fetching usage detail:", error);
					settle(entry?.data ?? null);
				});
		},
	}),
);

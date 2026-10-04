"use client";

import { useCallback, useSyncExternalStore } from "react";
import type { ViewMode } from "@/components/ui/view-toggle";

const listeners = new Map<string, Set<() => void>>();
const sessionValues = new Map<string, ViewMode>();

function read(storageKey: string, fallback: ViewMode): ViewMode {
	try {
		const stored = localStorage.getItem(storageKey);
		if (stored === "cards" || stored === "table") return stored;
	} catch {
		// Fall through to the in-session value.
	}
	return sessionValues.get(storageKey) ?? fallback;
}

export function usePersistedViewMode(
	storageKey: string,
	fallback: ViewMode = "table",
): readonly [ViewMode, (mode: ViewMode) => void] {
	const subscribe = useCallback(
		(listener: () => void) => {
			const subscribers = listeners.get(storageKey) ?? new Set<() => void>();
			subscribers.add(listener);
			listeners.set(storageKey, subscribers);
			return () => {
				subscribers.delete(listener);
				if (subscribers.size === 0) listeners.delete(storageKey);
			};
		},
		[storageKey],
	);
	const getSnapshot = useCallback(
		() => read(storageKey, fallback),
		[fallback, storageKey],
	);
	const getServerSnapshot = useCallback(() => fallback, [fallback]);
	const value = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

	const setValue = useCallback(
		(mode: ViewMode) => {
			sessionValues.set(storageKey, mode);
			try {
				localStorage.setItem(storageKey, mode);
			} catch {
				// Persistence failed; the in-session fallback still applies.
			}
			listeners.get(storageKey)?.forEach((listener) => {
				listener();
			});
		},
		[storageKey],
	);

	return [value, setValue] as const;
}

"use client";

import { useSyncExternalStore } from "react";

const RESPONSE_SOUND_KEY = "auxilia:play-response-sound";
const listeners = new Set<() => void>();

function readResponseSoundPreference(): boolean {
	if (typeof window === "undefined") return true;
	return window.localStorage.getItem(RESPONSE_SOUND_KEY) !== "false";
}

function subscribe(listener: () => void): () => void {
	listeners.add(listener);
	const handleStorage = (event: StorageEvent) => {
		if (event.key === RESPONSE_SOUND_KEY) listener();
	};
	window.addEventListener("storage", handleStorage);
	return () => {
		listeners.delete(listener);
		window.removeEventListener("storage", handleStorage);
	};
}

export function useResponseSoundEnabled(): boolean {
	return useSyncExternalStore(subscribe, readResponseSoundPreference, () => true);
}

export function isResponseSoundEnabled(): boolean {
	return readResponseSoundPreference();
}

export function setResponseSoundEnabled(enabled: boolean): void {
	window.localStorage.setItem(RESPONSE_SOUND_KEY, String(enabled));
	listeners.forEach((listener) => {
		listener();
	});
}

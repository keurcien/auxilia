"use client";

import { useSyncExternalStore } from "react";

const RESPONSE_SOUND_KEY = "auxilia:play-response-sound";
const SHOW_SHORTCUTS_IN_MENU_KEY = "auxilia:show-shortcuts-in-menu";
const responseSoundListeners = new Set<() => void>();
const shortcutsMenuListeners = new Set<() => void>();

function readResponseSoundPreference(): boolean {
	if (typeof window === "undefined") return true;
	return window.localStorage.getItem(RESPONSE_SOUND_KEY) !== "false";
}

function readShowShortcutsInMenuPreference(): boolean {
	if (typeof window === "undefined") return true;
	return window.localStorage.getItem(SHOW_SHORTCUTS_IN_MENU_KEY) !== "false";
}

function subscribeToPreference(
	key: string,
	listeners: Set<() => void>,
	listener: () => void,
): () => void {
	listeners.add(listener);
	const handleStorage = (event: StorageEvent) => {
		if (event.key === null || event.key === key) listener();
	};
	window.addEventListener("storage", handleStorage);
	return () => {
		listeners.delete(listener);
		window.removeEventListener("storage", handleStorage);
	};
}

function subscribeToResponseSound(listener: () => void): () => void {
	return subscribeToPreference(
		RESPONSE_SOUND_KEY,
		responseSoundListeners,
		listener,
	);
}

function subscribeToShortcutsMenu(listener: () => void): () => void {
	return subscribeToPreference(
		SHOW_SHORTCUTS_IN_MENU_KEY,
		shortcutsMenuListeners,
		listener,
	);
}

export function useResponseSoundEnabled(): boolean {
	return useSyncExternalStore(
		subscribeToResponseSound,
		readResponseSoundPreference,
		() => true,
	);
}

export function useShowShortcutsInMenu(): boolean {
	return useSyncExternalStore(
		subscribeToShortcutsMenu,
		readShowShortcutsInMenuPreference,
		() => true,
	);
}

export function isResponseSoundEnabled(): boolean {
	return readResponseSoundPreference();
}

export function setResponseSoundEnabled(enabled: boolean): void {
	window.localStorage.setItem(RESPONSE_SOUND_KEY, String(enabled));
	responseSoundListeners.forEach((listener) => {
		listener();
	});
}

export function setShowShortcutsInMenu(enabled: boolean): void {
	window.localStorage.setItem(SHOW_SHORTCUTS_IN_MENU_KEY, String(enabled));
	shortcutsMenuListeners.forEach((listener) => {
		listener();
	});
}

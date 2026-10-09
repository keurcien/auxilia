"use client";

import { useEffect } from "react";

let dirtyEditorCount = 0;
let forcedNavigationAllowed = false;

export function hasUnsavedChanges(): boolean {
	return dirtyEditorCount > 0;
}

export function prepareToDiscardUnsavedChanges(): boolean {
	if (!hasUnsavedChanges()) return true;
	if (!window.confirm("Discard unsaved changes?")) return false;
	forcedNavigationAllowed = true;
	return true;
}

export function cancelPreparedNavigation(): void {
	forcedNavigationAllowed = false;
}

export function useUnsavedChangesWarning(isDirty: boolean): void {
	useEffect(() => {
		if (!isDirty) return;
		dirtyEditorCount += 1;
		const warn = (event: BeforeUnloadEvent) => {
			if (!forcedNavigationAllowed) event.preventDefault();
		};
		window.addEventListener("beforeunload", warn);
		return () => {
			window.removeEventListener("beforeunload", warn);
			dirtyEditorCount = Math.max(0, dirtyEditorCount - 1);
			if (dirtyEditorCount === 0) forcedNavigationAllowed = false;
		};
	}, [isDirty]);
}

"use client";

import { useCallback, useState } from "react";
import { useSearchParams } from "next/navigation";

/**
 * Like useState, but mirrored into a URL query param so the value survives
 * back/forward navigation, refreshes, and can be deep-linked.
 *
 * Updates go through history.replaceState — a shallow URL rewrite with no
 * server round-trip and no history entry per keystroke. The param is read
 * once on mount (back navigation remounts the page, restoring the value);
 * when the value equals `defaultValue` the param is dropped from the URL.
 */
export function useQueryParamState(
	key: string,
	defaultValue = "",
): [string, (value: string) => void] {
	const searchParams = useSearchParams();
	const [value, setValue] = useState(
		() => searchParams.get(key) ?? defaultValue,
	);

	const update = useCallback(
		(next: string) => {
			setValue(next);
			const url = new URL(window.location.href);
			if (next && next !== defaultValue) {
				url.searchParams.set(key, next);
			} else {
				url.searchParams.delete(key);
			}
			window.history.replaceState(null, "", url);
		},
		[key, defaultValue],
	);

	return [value, update];
}

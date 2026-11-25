import { useCallback, useSyncExternalStore } from "react";
import type { GroupNode, GroupTree } from "@/lib/groups";

/**
 * Expanded/collapsed state of collapsible group sections, keyed by each
 * section's storage key and persisted in localStorage ("0" = collapsed).
 * Shared so a "Collapse all" control can drive every section of a view.
 */
const cache = new Map<string, boolean>();
const listeners = new Set<() => void>();

function read(key: string): boolean {
	const cached = cache.get(key);
	if (cached !== undefined) return cached;
	let expanded = true;
	try {
		expanded = localStorage.getItem(key) !== "0";
	} catch {
		// Without storage every section starts expanded.
	}
	cache.set(key, expanded);
	return expanded;
}

function subscribe(listener: () => void): () => void {
	listeners.add(listener);
	return () => {
		listeners.delete(listener);
	};
}

export function setGroupsExpanded(keys: string[], expanded: boolean): void {
	for (const key of keys) {
		cache.set(key, expanded);
		try {
			localStorage.setItem(key, expanded ? "1" : "0");
		} catch {
			// The in-session state still works when persistence is unavailable.
		}
	}
	for (const listener of listeners) listener();
}

export function useGroupExpanded(key: string): [boolean, () => void] {
	const expanded = useSyncExternalStore(
		subscribe,
		() => read(key),
		() => true,
	);
	const toggle = useCallback(() => {
		setGroupsExpanded([key], !read(key));
	}, [key]);
	return [expanded, toggle];
}

/** Whether every listed section is expanded. */
export function useAllGroupsExpanded(keys: string[]): boolean {
	return useSyncExternalStore(
		subscribe,
		() => keys.every(read),
		() => true,
	);
}

/**
 * Storage keys of every section a tree renders, following the convention of
 * the group components: a root group's key comes from `rootKey`, a nested
 * one appends `:${path}` to its parent's key.
 */
export function groupTreeStorageKeys<T>(
	tree: GroupTree<T>,
	rootKey: (path: string) => string,
): string[] {
	const keys: string[] = [];
	const visit = (node: GroupNode<T>, key: string) => {
		keys.push(key);
		for (const child of node.children) visit(child, `${key}:${child.path}`);
	};
	for (const group of tree.groups) visit(group, rootKey(group.path));
	if (tree.ungrouped.length > 0) keys.push(rootKey("__ungrouped__"));
	return keys;
}

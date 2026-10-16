"use client";

import { useEffect } from "react";
import { ensureSignedIn } from "@/lib/api/session";
import { useMcpServersStore } from "@/stores/mcp-servers-store";

export function StoreInitializer() {
	const { fetchMcpServers } = useMcpServersStore();

	useEffect(() => {
		// Initialize MCP servers store on app mount
		fetchMcpServers();
	}, [fetchMcpServers]);

	useEffect(() => {
		// A tab left open past the session's expiry finds out on return, not
		// on the first action that fails.
		const onVisible = () => {
			if (document.visibilityState === "visible") void ensureSignedIn();
		};
		// `focus` covers coming back from another app with the tab still visible.
		document.addEventListener("visibilitychange", onVisible);
		window.addEventListener("focus", onVisible);
		return () => {
			document.removeEventListener("visibilitychange", onVisible);
			window.removeEventListener("focus", onVisible);
		};
	}, []);

	return null;
}

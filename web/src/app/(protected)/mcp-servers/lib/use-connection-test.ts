"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/errors";
import { ConnectionTestResult, MCPAuthType } from "@/types/mcp-servers";

export type ConnectionTestStatus = "idle" | "testing" | "success" | "error";

// Only navigate a popup to http(s) URLs — reject javascript:/data: and other
// schemes so a malformed/hostile authorize URL can't execute script.
function toHttpUrl(value: string): string | null {
	try {
		const url = new URL(value);
		return url.protocol === "https:" || url.protocol === "http:"
			? url.href
			: null;
	} catch {
		return null;
	}
}

export interface CandidateTestInput {
	url: string;
	authType: MCPAuthType;
	apiKey?: string;
}

/**
 * Connection-test state machine shared by the list rows, the custom-server
 * form, and the detail page.
 *
 * `runSavedTest` tests a saved server as the current user — an unauthorized
 * OAuth server opens the authorize popup and polls `/is-connected` until the
 * user finishes (or 60s elapse). `runCandidateTest` probes unsaved form
 * values without persisting anything.
 */
export function useConnectionTest() {
	const [status, setStatus] = useState<ConnectionTestStatus>("idle");
	const [message, setMessage] = useState<string | null>(null);
	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	// Monotonic id so a result from a superseded run (config changed mid-test)
	// is ignored instead of overwriting the current state.
	const runRef = useRef(0);
	// One /is-connected probe at a time — a slow response must not overlap
	// with the next interval tick.
	const pollBusyRef = useRef(false);

	const clearPolling = useCallback(() => {
		if (pollRef.current) {
			clearInterval(pollRef.current);
			pollRef.current = null;
		}
		if (timeoutRef.current) {
			clearTimeout(timeoutRef.current);
			timeoutRef.current = null;
		}
	}, []);

	const reset = useCallback(() => {
		clearPolling();
		runRef.current++; // invalidate any in-flight run
		setStatus("idle");
		setMessage(null);
	}, [clearPolling]);

	// Stop polling if the component unmounts mid-authentication, and
	// invalidate the run so a late response can't restart timers afterwards.
	useEffect(() => {
		const runCounter = runRef;
		return () => {
			runCounter.current++;
			if (pollRef.current) clearInterval(pollRef.current);
			if (timeoutRef.current) clearTimeout(timeoutRef.current);
		};
	}, []);

	const applyResult = (data: ConnectionTestResult) => {
		if (data.reachable) {
			const count = data.toolCount ?? 0;
			setStatus("success");
			setMessage(
				`Connection successful — ${count} tool${count === 1 ? "" : "s"} available.`,
			);
		} else {
			setStatus("error");
			setMessage(data.error ?? "Could not connect to the server.");
		}
	};

	const runSavedTest = useCallback(
		async (server: { id: string; authType: MCPAuthType }) => {
			clearPolling();

			// A saved OAuth server may require interactive authorization. Popups
			// must be opened synchronously within the click to survive
			// Safari/Firefox blockers, so open a blank one now and navigate (or
			// close) it once the test result is known.
			let popup: Window | null = null;
			if (server.authType === "oauth2") {
				popup = window.open("", "_blank", "width=600,height=700");
				if (!popup) {
					setStatus("error");
					setMessage(
						"Popup blocked. Please allow popups for this site and try again.",
					);
					return;
				}
			}

			const runId = ++runRef.current;
			const isStale = () => runRef.current !== runId;
			setStatus("testing");
			setMessage(null);

			try {
				const { data } = await api.post<ConnectionTestResult>(
					`/mcp-servers/${server.id}/test-connection`,
				);
				if (isStale()) {
					popup?.close();
					return;
				}
				if (data.oauthRequired && data.authUrl) {
					const safeAuthUrl = toHttpUrl(data.authUrl);
					if (!safeAuthUrl) {
						popup?.close();
						setStatus("error");
						setMessage("Received an invalid authorization URL.");
						return;
					}
					if (popup) popup.location.href = safeAuthUrl;
					setMessage("Waiting for authentication…");
					pollBusyRef.current = false;
					pollRef.current = setInterval(() => {
						// Serialize probes: skip the tick while one is in flight.
						if (pollBusyRef.current) return;
						pollBusyRef.current = true;
						void (async () => {
							try {
								let connected = false;
								try {
									const res = await api.get(
										`/mcp-servers/${server.id}/is-connected`,
									);
									// Stale = a newer run owns the shared timers now — just
									// bail, clearing them would break that run.
									if (isStale()) return;
									connected = Boolean(res.data.connected);
								} catch {
									return; // transient — keep polling until timeout
								}
								if (!connected) return;
								clearPolling();
								if (popup && !popup.closed) popup.close();
								try {
									const retry = await api.post<ConnectionTestResult>(
										`/mcp-servers/${server.id}/test-connection`,
									);
									if (isStale()) return;
									applyResult(retry.data);
								} catch (error) {
									// Timers are already cleared — surface the failure
									// instead of leaving the button on "Testing…" forever.
									if (isStale()) return;
									setStatus("error");
									setMessage(
										getApiErrorMessage(error, "Failed to test connection."),
									);
								}
							} finally {
								// A superseded run must not release the flag — the shared
								// ref belongs to the current run's probes now.
								if (!isStale()) pollBusyRef.current = false;
							}
						})();
					}, 2000);
					timeoutRef.current = setTimeout(() => {
						clearPolling();
						if (isStale()) return;
						// Invalidate the run so an in-flight probe that resolves after
						// the deadline can't overwrite the timeout result.
						runRef.current++;
						setStatus("error");
						setMessage("Authentication timed out. Please try again.");
					}, 60000);
					return;
				}
				// No authorization needed — discard the pre-opened popup.
				popup?.close();
				applyResult(data);
			} catch (error) {
				popup?.close();
				if (isStale()) return;
				setStatus("error");
				setMessage(getApiErrorMessage(error, "Failed to test connection."));
			}
		},
		[clearPolling],
	);

	const runCandidateTest = useCallback(
		async (input: CandidateTestInput) => {
			clearPolling();
			const runId = ++runRef.current;
			const isStale = () => runRef.current !== runId;
			setStatus("testing");
			setMessage(null);

			try {
				const { data } = await api.post<ConnectionTestResult>(
					"/mcp-servers/test-connection",
					{
						url: input.url,
						authType: input.authType,
						apiKey:
							input.authType === "api_key"
								? input.apiKey || undefined
								: undefined,
					},
				);
				if (isStale()) return;
				applyResult(data);
			} catch (error) {
				if (isStale()) return;
				setStatus("error");
				setMessage(getApiErrorMessage(error, "Failed to test connection."));
			}
		},
		[clearPolling],
	);

	return { status, message, reset, runSavedTest, runCandidateTest };
}

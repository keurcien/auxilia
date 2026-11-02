"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useMcpOAuth } from "@/components/providers/mcp-oauth-provider";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import {
	ConnectionTestResult,
	MCPAuthType,
	ServiceCredentialProvider,
} from "@/types/mcp-servers";

export type ConnectionTestStatus = "idle" | "testing" | "success" | "error";

export interface CandidateTestInput {
	url: string;
	authType: MCPAuthType;
	apiKey?: string;
	serviceCredentialProvider?: ServiceCredentialProvider;
	serviceCredentialsJson?: string;
	serviceCredentialScopes?: string[];
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
	const { startAuthorization } = useMcpOAuth();
	const [status, setStatus] = useState<ConnectionTestStatus>("idle");
	const [message, setMessage] = useState<string | null>(null);
	const [oauthFollowUpOpen, setOauthFollowUpOpen] = useState(false);
	const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
	const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const followUpTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
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

	const clearFollowUpTimer = useCallback(() => {
		if (followUpTimerRef.current) {
			clearTimeout(followUpTimerRef.current);
			followUpTimerRef.current = null;
		}
	}, []);

	const reset = useCallback(() => {
		clearPolling();
		clearFollowUpTimer();
		runRef.current++; // invalidate any in-flight run
		setStatus("idle");
		setMessage(null);
		setOauthFollowUpOpen(false);
	}, [clearFollowUpTimer, clearPolling]);

	// Stop polling if the component unmounts mid-authentication, and
	// invalidate the run so a late response can't restart timers afterwards.
	useEffect(() => {
		const runCounter = runRef;
		return () => {
			runCounter.current++;
			if (pollRef.current) clearInterval(pollRef.current);
			if (timeoutRef.current) clearTimeout(timeoutRef.current);
			if (followUpTimerRef.current) clearTimeout(followUpTimerRef.current);
		};
	}, []);

	const applyResult = useCallback((data: ConnectionTestResult) => {
		if (data.reachable) {
			const count = data.toolCount ?? 0;
			setStatus("success");
			setMessage(
				`Connection successful. ${count} tool${count === 1 ? "" : "s"} available.`,
			);
		} else {
			setStatus("error");
			setMessage(data.error ?? "Could not connect to the server.");
		}
	}, []);

	const runSavedTest = useCallback(
		async (server: { id: string; name?: string; authType: MCPAuthType }) => {
			clearPolling();
			clearFollowUpTimer();
			setOauthFollowUpOpen(false);

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
				const data = await mcpServersApi.testMcpServerConnection(server.id);
				if (isStale()) {
					popup?.close();
					return;
				}
				if (data.oauthRequired && data.authUrl) {
					const started = startAuthorization({
						authUrl: data.authUrl,
						redirectMode: data.oauthRedirectMode,
						serverId: server.id,
						serverName: server.name,
						popup,
					});
					if (!started) {
						setStatus("error");
						setMessage("Could not open the authorization page.");
						return;
					}
					setMessage("Waiting for authentication…");
					if (data.oauthRedirectMode !== "loopback_manual") {
						followUpTimerRef.current = setTimeout(() => {
							if (!isStale()) setOauthFollowUpOpen(true);
							followUpTimerRef.current = null;
						}, 1000);
					}
					pollBusyRef.current = false;
					pollRef.current = setInterval(() => {
						// Serialize probes: skip the tick while one is in flight.
						if (pollBusyRef.current) return;
						pollBusyRef.current = true;
						void (async () => {
							try {
								let connected = false;
								try {
									const live = await mcpServersApi.isMcpServerConnected(server.id);
									// Stale = a newer run owns the shared timers now — just
									// bail, clearing them would break that run.
									if (isStale()) return;
									connected = live;
								} catch {
									return; // transient — keep polling until timeout
								}
								if (!connected) return;
								clearPolling();
								if (popup && !popup.closed) popup.close();
								try {
									const retry = await mcpServersApi.testMcpServerConnection(server.id);
									if (isStale()) return;
									applyResult(retry);
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
					}, data.oauthRedirectMode === "loopback_manual" ? 600000 : 60000);
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
		[applyResult, clearFollowUpTimer, clearPolling, startAuthorization],
	);

	const verifySavedConnection = useCallback(
		async (serverId: string): Promise<boolean> => {
			try {
				const data = await mcpServersApi.testMcpServerConnection(serverId);
				if (data.oauthRequired) {
					setStatus("testing");
					setMessage(
						"Authorization has not been detected yet. Finish OAuth, then try again.",
					);
					return false;
				}

				clearPolling();
				runRef.current++;
				applyResult(data);
				if (data.reachable) setOauthFollowUpOpen(false);
				return data.reachable;
			} catch (error) {
				setStatus("error");
				setMessage(getApiErrorMessage(error, "Failed to verify connection."));
				return false;
			}
		},
		[applyResult, clearPolling],
	);

	const runCandidateTest = useCallback(
		async (input: CandidateTestInput) => {
			clearPolling();
			const runId = ++runRef.current;
			const isStale = () => runRef.current !== runId;
			const usesServiceCredentials =
				input.authType === "service_identity" ||
				input.authType === "custom_http";
			setStatus("testing");
			setMessage(null);

			try {
				const data = await mcpServersApi.testMcpConnection({
					url: input.url,
					authType: input.authType,
					apiKey:
						input.authType === "api_key"
							? input.apiKey || undefined
							: undefined,
					serviceCredentialProvider:
						usesServiceCredentials
							? input.serviceCredentialProvider
							: undefined,
					serviceCredentialsJson:
						usesServiceCredentials ? input.serviceCredentialsJson : undefined,
					serviceCredentialScopes:
						usesServiceCredentials
							? input.serviceCredentialScopes
							: undefined,
				});
				if (isStale()) return;
				applyResult(data);
			} catch (error) {
				if (isStale()) return;
				setStatus("error");
				setMessage(getApiErrorMessage(error, "Failed to test connection."));
			}
		},
		[applyResult, clearPolling],
	);

	return {
		status,
		message,
		oauthFollowUpOpen,
		setOauthFollowUpOpen,
		reset,
		runSavedTest,
		verifySavedConnection,
		runCandidateTest,
	};
}

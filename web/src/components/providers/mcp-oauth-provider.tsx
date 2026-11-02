"use client";

import {
	createContext,
	useCallback,
	useContext,
	useMemo,
	useRef,
	useState,
} from "react";
import { AlertTriangle, Loader2, LockKeyhole } from "lucide-react";
import { toast } from "sonner";
import {
	Dialog,
	DialogButton,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import type {
	OAuthManualCallbackResponse,
	OAuthRedirectMode,
} from "@/types/mcp-servers";

interface OAuthAuthorizationRequest {
	authUrl: string;
	redirectMode?: OAuthRedirectMode;
	serverId?: string;
	serverName?: string;
	popup?: Window | null;
	onSuccess?: (result: OAuthManualCallbackResponse) => void | Promise<void>;
}

interface ManualAttempt extends OAuthAuthorizationRequest {
	popup: Window;
}

interface McpOAuthContextValue {
	startAuthorization: (request: OAuthAuthorizationRequest) => boolean;
}

const McpOAuthContext = createContext<McpOAuthContextValue | null>(null);

function safeAuthorizationUrl(value: string): string | null {
	try {
		const url = new URL(value);
		return url.protocol === "https:" || url.protocol === "http:"
			? url.href
			: null;
	} catch {
		return null;
	}
}

export function McpOAuthProvider({ children }: { children: React.ReactNode }) {
	const [manualAttempt, setManualAttempt] = useState<ManualAttempt | null>(null);
	const [callbackUrl, setCallbackUrl] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);
	const manualPopupRef = useRef<Window | null>(null);

	const closeManualAttempt = useCallback(() => {
		if (manualPopupRef.current && !manualPopupRef.current.closed) {
			manualPopupRef.current.close();
		}
		manualPopupRef.current = null;
		setManualAttempt(null);
		setCallbackUrl("");
		setError(null);
		setSubmitting(false);
	}, []);

	const startAuthorization = useCallback(
		(request: OAuthAuthorizationRequest): boolean => {
			const authUrl = safeAuthorizationUrl(request.authUrl);
			if (!authUrl) {
				request.popup?.close();
				toast.error("The authorization URL is invalid.");
				return false;
			}

			const popup =
				request.popup ??
				window.open(
					"",
					"_blank",
					request.redirectMode === "loopback_manual"
						? undefined
						: "width=600,height=700",
				);
			if (!popup) {
				toast.error("Allow pop-ups for this site, then try again.");
				return false;
			}
			popup.location.href = authUrl;

			if (request.redirectMode === "loopback_manual") {
				if (manualPopupRef.current && !manualPopupRef.current.closed) {
					manualPopupRef.current.close();
				}
				manualPopupRef.current = popup;
				setCallbackUrl("");
				setError(null);
				setSubmitting(false);
				setManualAttempt({ ...request, popup });
			}
			return true;
		},
		[],
	);

	const finishManualConnection = useCallback(async () => {
		if (!manualAttempt || submitting) return;
		const value = callbackUrl.trim();
		if (!value) {
			setError("Paste the complete address from your browser.");
			return;
		}
		setSubmitting(true);
		setError(null);
		let result: OAuthManualCallbackResponse;
		try {
			result = await mcpServersApi.completeManualOAuth(value);
		} catch (caught: unknown) {
			setError(
				getApiErrorMessage(
					caught,
					"Could not finish the connection. Restart authorization and try again.",
				),
			);
			setSubmitting(false);
			return;
		}
		const onSuccess = manualAttempt.onSuccess;
		if (!manualAttempt.popup.closed) manualAttempt.popup.close();
		manualPopupRef.current = null;
		setManualAttempt(null);
		setCallbackUrl("");
		setSubmitting(false);
		toast.success(`${result.serverName} is connected.`);
		try {
			await onSuccess?.(result);
		} catch {
			toast.error("Connected, but this page could not refresh automatically.");
		}
	}, [callbackUrl, manualAttempt, submitting]);

	const value = useMemo(
		() => ({ startAuthorization }),
		[startAuthorization],
	);

	return (
		<McpOAuthContext.Provider value={value}>
			{children}
			<Dialog
				open={manualAttempt !== null}
				onOpenChange={(open) => {
					if (!open && !submitting) closeManualAttempt();
				}}
			>
				<DialogContent>
					<DialogHeader>
						<DialogTitle>Authentication is almost complete</DialogTitle>
						<DialogDescription>
							Complete authentication in the new browser tab. The browser may
							say it cannot connect to 127.0.0.1. This is expected.
						</DialogDescription>
					</DialogHeader>

					<div className="space-y-4">
						<div className="rounded-[10px] border border-border bg-hover/60 p-3.5 dark:bg-white/5">
							<div className="flex gap-3">
								<LockKeyhole className="mt-0.5 size-4 shrink-0 text-petrol dark:text-panel-terminal" />
								<div className="space-y-1.5 text-[12.5px] leading-[1.55] text-subtle dark:text-panel-body">
									<p>
										Copy the complete address currently shown in your
										browser&apos;s address bar, then paste it below.
									</p>
									<p>You do not need to install or run anything.</p>
								</div>
							</div>
						</div>

						<div>
							<label
								htmlFor="manual-oauth-callback-url"
								className="text-[12px] font-semibold text-foreground"
							>
								Browser address
							</label>
							<Textarea
								id="manual-oauth-callback-url"
								value={callbackUrl}
								onChange={(event) => {
									setCallbackUrl(event.target.value);
									if (error) setError(null);
								}}
								placeholder="http://127.0.0.1:4789/oauth/callback?code=…&state=…"
								autoComplete="off"
								autoCapitalize="none"
								spellCheck={false}
								disabled={submitting}
								aria-invalid={Boolean(error)}
								className="mt-1.5 min-h-24 resize-y font-mono text-[12px] leading-[1.5]"
							/>
						</div>

						<div className="flex gap-2.5 text-[11.5px] leading-[1.5] text-meta dark:text-panel-dim">
							<AlertTriangle className="mt-0.5 size-3.5 shrink-0" />
							<p>
								This address is sensitive and temporary. Do not share it with
								anyone.
							</p>
						</div>

						{error && (
							<p
								className="rounded-[8px] bg-destructive/8 px-3 py-2.5 text-[12px] leading-[1.5] text-destructive"
								role="alert"
							>
								{error}
							</p>
						)}
					</div>

					<DialogFooter className="flex-col-reverse sm:flex-row">
						<DialogButton
							variant="outline"
							className="w-full sm:w-auto"
							onClick={closeManualAttempt}
							disabled={submitting}
						>
							Cancel
						</DialogButton>
						<DialogButton
							className="w-full sm:w-auto"
							onClick={() => {
								void finishManualConnection();
							}}
							disabled={submitting || !callbackUrl.trim()}
						>
							{submitting && <Loader2 className="size-3.5 animate-spin" />}
							{submitting ? "Finishing connection…" : "Finish connection"}
						</DialogButton>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</McpOAuthContext.Provider>
	);
}

export function useMcpOAuth() {
	const context = useContext(McpOAuthContext);
	if (!context) {
		throw new Error("useMcpOAuth must be used within McpOAuthProvider");
	}
	return context;
}

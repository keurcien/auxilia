"use client";

import { useCallback, useEffect, useState } from "react";
import {
	CircleAlert,
	ExternalLink,
	KeyRound,
	RefreshCw,
	Wrench,
} from "lucide-react";
import { useMcpOAuth } from "@/components/providers/mcp-oauth-provider";
import { Switch } from "@/components/ui/switch";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import type {
	MCPServerTool,
	MCPToolLoadError,
	OAuthRedirectMode,
} from "@/types/mcp-servers";
import { cn } from "@/lib/utils";
import {
	PersonalCredentialsDialog,
	type PersonalCredentialsServer,
} from "./personal-credentials-dialog";

interface MCPServerToolsPanelProps {
	serverId: string;
	/** Set for a personal API-key / custom HTTP server: the user may be asked
	 * for their own secret before the tools can be listed. */
	credentialsServer?: PersonalCredentialsServer;
	disabledTools: string[];
	onDisabledToolsChange?: (tools: string[]) => void;
	disabled?: boolean;
	readOnly?: boolean;
}

export function MCPServerToolsPanel({
	serverId,
	credentialsServer,
	disabledTools,
	onDisabledToolsChange,
	disabled = false,
	readOnly = false,
}: MCPServerToolsPanelProps) {
	const { startAuthorization } = useMcpOAuth();
	const [tools, setTools] = useState<MCPServerTool[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [error, setError] = useState<MCPToolLoadError | null>(null);
	const [authUrl, setAuthUrl] = useState<string | null>(null);
	const [authSignInUrl, setAuthSignInUrl] = useState<string | null>(null);
	const [authRedirectMode, setAuthRedirectMode] =
		useState<OAuthRedirectMode>("hosted_callback");
	const [needsCredentials, setNeedsCredentials] = useState(false);
	const [credentialsOpen, setCredentialsOpen] = useState(false);

	const loadTools = useCallback(async () => {
		setIsLoading(true);
		setError(null);
		setNeedsCredentials(false);
		try {
			const result = await mcpServersApi.listMcpServerTools(serverId);
			if (result.status === "error") {
				setTools([]);
				setAuthUrl(null);
				setAuthSignInUrl(null);
				setError(result);
				return;
			}
			if (result.status === "credentials_required") {
				setTools([]);
				setAuthUrl(null);
				setAuthSignInUrl(null);
				setNeedsCredentials(true);
				return;
			}
			if (result.status === "auth_required") {
				setTools([]);
				setAuthUrl(result.authUrl);
				setAuthSignInUrl(result.oauthSignInUrl ?? null);
				setAuthRedirectMode(result.oauthRedirectMode);
				return;
			}
			setAuthUrl(null);
			setAuthSignInUrl(null);
			setTools(result.tools);
		} catch (loadError: unknown) {
			setError({
				status: "error",
				code: "request_failed",
				title: "Tools could not be loaded",
				detail: getApiErrorMessage(
					loadError,
					"Auxilia could not reach the MCP server.",
				),
				action: "Check your connection and try again.",
				retryable: true,
			});
		} finally {
			setIsLoading(false);
		}
	}, [serverId]);

	useEffect(() => {
		void loadTools();
	}, [loadTools]);

	const disabledSet = new Set(disabledTools);
	const enabledCount = tools.filter((tool) => !disabledSet.has(tool.name)).length;

	const setToolEnabled = (toolName: string, enabled: boolean) => {
		if (!onDisabledToolsChange) return;
		if (enabled) {
			onDisabledToolsChange(disabledTools.filter((name) => name !== toolName));
			return;
		}
		onDisabledToolsChange([...new Set([...disabledTools, toolName])]);
	};

	return (
		<div className="flex min-h-0 flex-1 flex-col">
			<div className="flex items-start justify-between gap-4 border-b border-hairline pb-4 dark:border-white/5">
				<div>
					<div className="flex items-center gap-2">
						<Wrench className="size-3.5 text-petrol dark:text-panel-terminal" />
						<h2 className="text-[13px] font-semibold text-foreground">Tools</h2>
					</div>
					<p className="mt-1.5 max-w-md text-[12.5px] leading-[1.5] text-meta dark:text-panel-dim">
						{readOnly
							? "Availability across every agent using this server."
							: "Disabled tools are unavailable to every agent using this server."}
					</p>
				</div>
				{tools.length > 0 && (
					<span className="shrink-0 rounded-[4px] bg-hover px-2.5 py-1 text-[10.5px] font-semibold text-subtle dark:bg-white/10 dark:text-panel-body">
						{enabledCount}/{tools.length} enabled
					</span>
				)}
			</div>

			<div className="min-h-0 flex-1 overflow-y-auto py-3 [scrollbar-width:thin]">
				{isLoading ? (
					<div className="flex flex-col gap-2.5">
						{[0, 1, 2, 3].map((item) => (
							<div
								key={item}
								className="h-[66px] animate-pulse rounded-[10px] bg-hover dark:bg-white/5"
							/>
						))}
					</div>
				) : error ? (
					<div className="rounded-[10px] border border-destructive/20 bg-destructive/5 p-4">
						<div className="flex items-start gap-2.5">
							<CircleAlert className="mt-0.5 size-4 shrink-0 text-destructive" />
							<div className="min-w-0">
								<p className="text-[13px] font-semibold text-foreground">
									{error.title}
								</p>
								<p className="mt-1 text-[12.5px] leading-[1.5] text-meta dark:text-panel-dim">
									{error.detail}
								</p>
								{error.action && (
									<p className="mt-2 text-[12.5px] font-medium leading-[1.5] text-foreground">
										{error.action}
									</p>
								)}
							</div>
						</div>
						<button
							type="button"
							onClick={() => {
								void loadTools();
							}}
							className="mt-3 inline-flex cursor-pointer items-center gap-1.5 text-[12px] font-semibold text-petrol hover:opacity-80 dark:text-panel-terminal"
						>
							<RefreshCw className="size-3" />
							{error.retryable ? "Try again" : "Check again"}
						</button>
					</div>
				) : needsCredentials ? (
					<div className="rounded-[12px] border border-dashed border-input p-6 text-center">
						<p className="text-[13px] font-semibold text-foreground">
							Connect to list tools
						</p>
						<p className="mt-1.5 text-[12px] leading-[1.5] text-meta dark:text-panel-dim">
							{credentialsServer?.authType === "api_key"
								? "This server uses a personal API key. Enter yours to list the tools."
								: "This server uses personal HTTP headers. Enter your values to list the tools."}
						</p>
						{credentialsServer && (
							<button
								type="button"
								onClick={() => {
									setCredentialsOpen(true);
								}}
								className="mt-4 inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-petrol px-3 py-2 text-[12px] font-semibold text-white hover:opacity-90"
							>
								<KeyRound className="size-3" />
								Enter credentials
							</button>
						)}
					</div>
				) : authUrl ? (
					<div className="rounded-[12px] border border-dashed border-input p-6 text-center">
						<p className="text-[13px] font-semibold text-foreground">
							Connect to list tools
						</p>
						<p className="mt-1.5 text-[12px] leading-[1.5] text-meta dark:text-panel-dim">
							Authorize your account, then refresh the list.
						</p>
						<div className="mt-4 flex flex-wrap justify-center gap-2">
							<button
								type="button"
								onClick={() => {
									startAuthorization({
										authUrl,
										redirectMode: authRedirectMode,
										signInUrl: authSignInUrl,
										serverId,
										onSuccess: async () => {
											await loadTools();
										},
									});
								}}
								className="inline-flex cursor-pointer items-center gap-1.5 rounded-[7px] bg-petrol px-3 py-2 text-[12px] font-semibold text-white hover:opacity-90"
							>
								Authorize
								<ExternalLink className="size-3" />
							</button>
							<button
								type="button"
								onClick={() => {
									void loadTools();
								}}
								className="cursor-pointer rounded-[7px] border border-input px-3 py-2 text-[12px] font-semibold text-foreground hover:bg-hover dark:hover:bg-white/5"
							>
								Refresh tools
							</button>
						</div>
					</div>
				) : tools.length === 0 ? (
					<div className="rounded-[10px] border border-dashed border-input px-4 py-8 text-center text-[13px] text-meta dark:text-panel-dim">
						This server exposes no tools.
					</div>
				) : (
					<div className="overflow-hidden rounded-[10px] border border-border bg-card">
						{tools.map((tool) => {
							const enabled = !disabledSet.has(tool.name);
							return (
								<div
									key={tool.name}
									className="flex items-center gap-2.5 border-b border-hover px-4 py-2.5 last:border-b-0 dark:border-white/5"
								>
									<span className="min-w-0 flex-1">
										<span
											className={cn(
												"block truncate text-[13.5px] font-semibold",
												enabled
													? "text-foreground"
													: "text-meta dark:text-panel-dim",
											)}
										>
											{humanizeToolName(tool.name)}
										</span>
										{tool.description && (
											<span
												className={cn(
													"mt-px line-clamp-2 text-xs",
													enabled
														? "text-muted-foreground"
														: "text-faint dark:text-panel-dim",
												)}
											>
												{tool.description}
											</span>
										)}
									</span>
									{readOnly ? (
										<span
											className={`inline-flex shrink-0 items-center gap-1.5 rounded-[4px] px-2 py-[3px] text-[9.5px] font-semibold ${
												enabled
													? "bg-success-bg text-success dark:bg-emerald-950 dark:text-emerald-300"
													: "bg-hover text-meta dark:bg-white/10 dark:text-panel-dim"
											}`}
										>
											<span
												className={`size-[5px] rounded-full ${
													enabled ? "bg-success" : "bg-meta"
												}`}
											/>
											{enabled ? "Active" : "Inactive"}
										</span>
									) : (
										<Switch
											checked={enabled}
											disabled={disabled}
											onCheckedChange={(checked) => {
												setToolEnabled(tool.name, checked);
											}}
											aria-label={`${enabled ? "Disable" : "Enable"} ${tool.name}`}
											className="data-[state=checked]:bg-petrol"
										/>
									)}
								</div>
							);
						})}
					</div>
				)}
			</div>
			{credentialsServer && (
				<PersonalCredentialsDialog
					server={credentialsOpen ? credentialsServer : null}
					onOpenChange={setCredentialsOpen}
					onSaved={() => {
						setCredentialsOpen(false);
						void loadTools();
					}}
				/>
			)}
		</div>
	);
}

"use client";

import { useCallback, useEffect, useState } from "react";
import { ExternalLink, RefreshCw, Wrench } from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { humanizeToolName } from "@/components/ai-elements/chain-of-thought";
import * as mcpServersApi from "@/lib/api/resources/mcp-servers";
import { getApiErrorMessage } from "@/lib/api/errors";
import type { MCPServerTool } from "@/types/mcp-servers";
import { cn } from "@/lib/utils";

interface MCPServerToolsPanelProps {
	serverId: string;
	disabledTools: string[];
	onDisabledToolsChange?: (tools: string[]) => void;
	disabled?: boolean;
	readOnly?: boolean;
}

export function MCPServerToolsPanel({
	serverId,
	disabledTools,
	onDisabledToolsChange,
	disabled = false,
	readOnly = false,
}: MCPServerToolsPanelProps) {
	const [tools, setTools] = useState<MCPServerTool[]>([]);
	const [isLoading, setIsLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [authUrl, setAuthUrl] = useState<string | null>(null);

	const loadTools = useCallback(async () => {
		setIsLoading(true);
		setError(null);
		try {
			const result = await mcpServersApi.listMcpServerTools(serverId);
			if (result.status === "auth_required") {
				setTools([]);
				setAuthUrl(result.authUrl);
				return;
			}
			setAuthUrl(null);
			setTools(result.tools);
		} catch (loadError: unknown) {
			setError(getApiErrorMessage(loadError, "Failed to load tools."));
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
						<p className="text-[12.5px] text-destructive">{error}</p>
						<button
							type="button"
							onClick={() => {
								void loadTools();
							}}
							className="mt-3 inline-flex cursor-pointer items-center gap-1.5 text-[12px] font-semibold text-petrol hover:opacity-80 dark:text-panel-terminal"
						>
							<RefreshCw className="size-3" />
							Try again
						</button>
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
									window.open(authUrl, "_blank", "width=600,height=700");
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
		</div>
	);
}

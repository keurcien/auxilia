"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import { MCPServer } from "@/types/mcp-servers";
import { ToolStatus } from "@/types/agents";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import AgentMCPTool from "./agent-mcp-tool";
import { AgentMCPServerForm } from "../../lib/agent-form";
import { api } from "@/lib/api/client";

interface AgentMCPServerProps {
	server: MCPServer;
	binding: AgentMCPServerForm;
	readOnly?: boolean;
	/** Draft update: the complete per-tool map for this server. */
	onToolsChange?: (tools: Record<string, ToolStatus>) => void;
	/** Draft update: detach this server. */
	onRemove?: () => void;
}

interface MCPServerTool {
	name: string;
	description?: string;
}

export default function AgentMCPServer({
	server,
	binding,
	readOnly,
	onToolsChange,
	onRemove,
}: AgentMCPServerProps) {
	const [isExpanded, setIsExpanded] = useState(false);
	const [tools, setTools] = useState<MCPServerTool[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [toolsFetched, setToolsFetched] = useState(false);
	const [isConnected, setIsConnected] = useState(false);
	const [isCheckingConnection, setIsCheckingConnection] = useState(true);

	// Auto-expand when not connected
	useEffect(() => {
		if (!isCheckingConnection && !isConnected) {
			setIsExpanded(true);
		}
	}, [isCheckingConnection, isConnected]);

	const handleToggleExpand = () => {
		setIsExpanded(!isExpanded);
	};

	const statusFor = (toolName: string): ToolStatus => {
		// Object.hasOwn (not `in`) so a tool literally named "toString" etc.
		// can't match an inherited prototype member and return a non-status.
		if (binding.tools && Object.hasOwn(binding.tools, toolName)) {
			return binding.tools[toolName];
		}
		return "always_allow";
	};

	// The complete-map rule: the draft's tools map stays null until the user
	// actually edits, then it materializes from the fetched tool list so a
	// Save never sends a partial map (the backend does whole-map replace).
	const materializeTools = useCallback(
		(fetchedTools: MCPServerTool[]): Record<string, ToolStatus> => {
			const full: Record<string, ToolStatus> = Object.fromEntries(
				fetchedTools.map((tool) => [tool.name, "always_allow" as ToolStatus]),
			);
			return { ...full, ...(binding.tools ?? {}) };
		},
		[binding.tools],
	);

	const handleStatusChange = (toolName: string, status: ToolStatus) => {
		if (readOnly) return;
		onToolsChange?.({ ...materializeTools(tools), [toolName]: status });
	};

	const fetchTools = useCallback(async () => {
		setIsLoading(true);
		try {
			const res = await api.get(`/mcp-servers/${server.id}/list-tools`);
			const fetchedTools = res.data as MCPServerTool[];
			setTools(fetchedTools);
			setToolsFetched(true);
		} catch (error: unknown) {
			// Check if this is an OAuth authorization required error
			if (
				error &&
				typeof error === "object" &&
				"response" in error &&
				error.response &&
				typeof error.response === "object" &&
				"status" in error.response &&
				error.response.status === 401 &&
				"data" in error.response &&
				error.response.data &&
				typeof error.response.data === "object" &&
				"auth_url" in error.response.data
			) {
				const authUrl = error.response.data.auth_url as string;

				const popup = window.open(authUrl, "_blank", "width=600,height=700");

				const poll = async () => {
					try {
						const statusRes = await api.get(
							`/mcp-servers/${server.id}/is-connected-v2`,
						);
						const statusData = statusRes.data;

						if (statusData.connected) {
							clearInterval(pollInterval);
							setIsConnected(true);

							// Fetch tools for display; connecting is a deliberate
							// action, so it also seeds the draft's tool map when
							// the binding was never synced.
							const retryRes = await api.get(
								`/mcp-servers/${server.id}/list-tools`,
							);
							const fetchedTools = retryRes.data as MCPServerTool[];
							setTools(fetchedTools);
							setToolsFetched(true);
							setIsLoading(false);

							if (!readOnly && binding.tools === null) {
								onToolsChange?.(
									Object.fromEntries(
										fetchedTools.map((tool) => [
											tool.name,
											"always_allow" as ToolStatus,
										]),
									),
								);
							}

							if (popup && !popup.closed) {
								popup.close();
							}
						}
					} catch (pollError) {
						console.error("Error polling connection status:", pollError);
					}
				};
				const pollInterval = setInterval(() => {
					void poll();
				}, 2000);

				setTimeout(() => {
					clearInterval(pollInterval);
					setIsLoading(false);
				}, 60000);

				return;
			}

			console.error("Failed to fetch tools:", error);
			setTools([]);
		} finally {
			setIsLoading(false);
		}
	}, [server.id, readOnly, binding.tools, onToolsChange]);

	const handleConnect = async () => {
		await fetchTools();
	};

	useEffect(() => {
		setIsCheckingConnection(true);
		api
			.get(`/mcp-servers/${server.id}/is-connected-v2`)
			.then((res) => {
				setIsConnected(res.data.connected);
			})
			.catch((error) => {
				console.error("Failed to check connection status:", error);
				setIsConnected(false);
			})
			.finally(() => {
				setIsCheckingConnection(false);
			});
	}, [server.id]);

	// Fetch tools on initial load if the server is connected
	useEffect(() => {
		if (!toolsFetched && isConnected) {
			fetchTools();
		}
	}, [toolsFetched, isConnected, fetchTools]);

	return (
		<div className="border-b last:border-b-0">
			<div className="flex items-center p-3 hover:bg-[#F8FAF9] dark:hover:bg-white/5 transition-colors">
				<div className="w-6 h-6 rounded-sm flex items-center justify-center text-white font-semibold mr-3 overflow-hidden relative">
					<Image
						unoptimized
						width={24}
						height={24}
						src={
							server.iconUrl ??
							"https://storage.googleapis.com/choose-assets/mcp.png"
						}
						alt={server.name}
						className="object-cover"
					/>
				</div>

				<div className="flex-1">
					<div className="flex items-center gap-2">
						<div className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground">{server.name}</div>
						{isCheckingConnection ? (
							<Badge
								variant="secondary"
								className="bg-muted text-muted-foreground border-border text-[0.6rem]"
							>
								<span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/60" />
								Checking
							</Badge>
						) : isConnected ? (
							<Badge
								variant="secondary"
								className="bg-green-100 dark:bg-green-950/40 text-green-600 dark:text-green-400 border-green-200 dark:border-green-800 text-[0.6rem]"
							>
								<span className="w-1.5 h-1.5 rounded-full bg-green-400" />
								Ready
							</Badge>
						) : (
							<Badge
								variant="destructive"
								className="bg-red-100 dark:bg-red-950/40 text-red-600 dark:text-red-400 border-red-200 dark:border-red-800 text-[0.6rem]"
							>
								<span className="w-1.5 h-1.5 rounded-full bg-red-400" />
								Not Connected
							</Badge>
						)}
					</div>
				</div>

				<button
					onClick={handleToggleExpand}
					className="text-muted-foreground hover:text-foreground cursor-pointer p-1"
				>
					<ChevronRight
						className={`w-5 h-5 transition-transform ${
							isExpanded ? "rotate-90" : ""
						}`}
					/>
				</button>
			</div>

			{isExpanded && (
				<div className="bg-card p-4 border-t">
					<div className="max-h-[400px] overflow-y-auto mb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
						{!isConnected ? (
							<div className="rounded-2xl border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-[#FAFCFB] dark:bg-white/5 p-6 text-center mb-3">
								<div className="w-10 h-10 rounded-full bg-[#F5F8F6] dark:bg-white/10 border-[1.5px] border-[#E0E8E4] dark:border-white/10 flex items-center justify-center mx-auto mb-3">
									<svg width="18" height="18" viewBox="0 0 20 20" fill="none">
										<rect
											x="4"
											y="9"
											width="12"
											height="9"
											rx="2"
											stroke="currentColor"
											strokeWidth="1.5"
											className="text-[#6B7F76] dark:text-muted-foreground"
										/>
										<path
											d="M7 9V6a3 3 0 116 0v3"
											stroke="currentColor"
											strokeWidth="1.5"
											strokeLinecap="round"
											className="text-[#6B7F76] dark:text-muted-foreground"
										/>
									</svg>
								</div>
								<p className="font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground mb-1">Connect your account</p>
								<p className="font-[family-name:var(--font-dm-sans)] text-[12px] text-[#A3B5AD] dark:text-muted-foreground mb-4">
									This server requires authentication.
								</p>
								<button
									className="px-5 py-2.5 bg-[#111111] dark:bg-white text-white dark:text-[#111111] font-[family-name:var(--font-dm-sans)] text-[13px] font-semibold rounded-full hover:opacity-90 transition-all cursor-pointer"
									onClick={() => {
										void handleConnect();
									}}
								>
									Connect
								</button>
							</div>
						) : isLoading ? (
							<div className="text-sm text-muted-foreground py-2">
								Loading tools...
							</div>
						) : tools && tools.length > 0 ? (
							<div className="space-y-2">
								{tools.map((tool) => (
									<AgentMCPTool
										key={tool.name}
										toolName={tool.name}
										toolDescription={tool.description}
										status={statusFor(tool.name)}
										readOnly={readOnly}
										onStatusChange={(status) => {
											handleStatusChange(tool.name, status);
										}}
									/>
								))}
							</div>
						) : (
							<div className="text-sm text-muted-foreground py-2">
								No tools available
							</div>
						)}
					</div>
					{!readOnly && (
						<div className="flex w-full justify-center">
							<Button
								variant="ghost"
								size="sm"
								className="text-destructive cursor-pointer hover:text-destructive/80"
								onClick={() => {
									onRemove?.();
								}}
							>
								Disable {server.name}
							</Button>
						</div>
					)}
				</div>
			)}
		</div>
	);
}

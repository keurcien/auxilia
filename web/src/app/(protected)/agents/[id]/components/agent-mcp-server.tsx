"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import { MCPServer } from "@/types/mcp-servers";
import { Agent } from "@/types/agents";
import { ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import AgentMCPTool from "./agent-mcp-tool";
import { api } from "@/lib/api/client";

interface AgentMCPServerProps {
	agent: Agent;
	server: MCPServer;
	onUpdate?: () => void;
}

interface MCPServerTool {
	name: string;
	description?: string;
}

export default function AgentMCPServer({
	agent,
	server,
	onUpdate,
}: AgentMCPServerProps) {
	const initialAttached =
		agent.mcpServers?.some((s) => s.id === server.id) || false;
	const [isAttached, setIsAttached] = useState(initialAttached);
	const [isExpanded, setIsExpanded] = useState(false);
	const [tools, setTools] = useState<MCPServerTool[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [toolsFetched, setToolsFetched] = useState(false);
	const [isConnected, setIsConnected] = useState(false);
	const [isCheckingConnection, setIsCheckingConnection] = useState(true);

	const handleToggleServer = async (serverId: string, isEnabled: boolean) => {
		setIsAttached(isEnabled);

		try {
			if (isEnabled) {
				await api.post(`/agents/${agent.id}/mcp-servers/${serverId}`, {});

				// Notify parent to update
				onUpdate?.();

				if (!toolsFetched) {
					await fetchTools();
				}
			} else {
				await api.delete(`/agents/${agent.id}/mcp-servers/${serverId}`);

				// Notify parent to update
				onUpdate?.();
			}
		} catch (error) {
			console.error("Failed to toggle server:", error);
			setIsAttached(!isEnabled);
		}
	};

	const handleToggleExpand = () => {
		setIsExpanded(!isExpanded);
	};

	const fetchTools = useCallback(async () => {
		setIsLoading(true);
		try {
			const res = await api.get(`/mcp-servers/${server.id}/list-tools`);
			const fetchedTools = res.data;
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

				const pollInterval = setInterval(async () => {
					try {
						const statusRes = await api.get(
							`/mcp-servers/${server.id}/is-connected`,
						);
						const statusData = statusRes.data;

						if (statusData.connected) {
							clearInterval(pollInterval);
							setIsConnected(true);
							setIsAttached(true);

							// Sync tools to the binding (saves with always_allow)
							await api.post(
								`/agents/${agent.id}/mcp-servers/${server.id}/sync-tools`,
							);

							// Fetch tools for display
							const retryRes = await api.get(
								`/mcp-servers/${server.id}/list-tools`,
							);
							const fetchedTools = retryRes.data;
							setTools(fetchedTools);
							setToolsFetched(true);
							setIsLoading(false);

							// Notify parent to refresh agent data with updated tools
							onUpdate?.();

							if (popup && !popup.closed) {
								popup.close();
							}
						}
					} catch (pollError) {
						console.error("Error polling connection status:", pollError);
					}
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
	}, [server.id, agent.id, onUpdate]);

	const handleConnect = async () => {
		await fetchTools();
	};

	useEffect(() => {
		setIsCheckingConnection(true);
		api
			.get(`/mcp-servers/${server.id}/is-connected`)
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

	// Fetch tools on initial load if server is already attached
	useEffect(() => {
		if (isAttached && !toolsFetched && isConnected) {
			fetchTools();
		}
	}, [isAttached, toolsFetched, isConnected, fetchTools]);

	return (
		<div className="border-b last:border-b-0">
			<div className="flex items-center p-3 hover:bg-gray-50">
				<div className="w-6 h-6 rounded-sm flex items-center justify-center text-white font-semibold mr-3 overflow-hidden relative">
					<Image
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
						<div className="text-sm">{server.name}</div>
						{isCheckingConnection ? (
							<Badge
								variant="secondary"
								className="bg-gray-100 text-gray-600 border-gray-200 text-[0.6rem]"
							>
								<span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
								Checking
							</Badge>
						) : isConnected ? (
							<Badge
								variant="secondary"
								className="bg-green-100 text-green-600 border-green-200 text-[0.6rem]"
							>
								<span className="w-1.5 h-1.5 rounded-full bg-green-400" />
								Ready
							</Badge>
						) : (
							<Badge
								variant="destructive"
								className="bg-red-100 text-red-600 border-red-200 text-[0.6rem]"
							>
								<span className="w-1.5 h-1.5 rounded-full bg-red-400" />
								Not Connected
							</Badge>
						)}
					</div>
				</div>

				<button
					onClick={handleToggleExpand}
					className="text-gray-500 hover:text-gray-700 cursor-pointer p-1"
				>
					<ChevronRight
						className={`w-5 h-5 transition-transform ${
							isExpanded ? "rotate-90" : ""
						}`}
					/>
				</button>
			</div>

			{isExpanded && (
				<div className="bg-white p-4 border-t">
					<div className="max-h-[400px] overflow-y-auto mb-3 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
						{!isConnected ? (
							<div className="bg-gray-50 rounded-xl p-5 text-center mb-3">
								<div className="w-10 h-10 bg-gray-100 rounded-xl flex items-center justify-center mx-auto mb-3">
									<svg width="20" height="20" viewBox="0 0 20 20" fill="none">
										<rect
											x="4"
											y="9"
											width="12"
											height="9"
											rx="2"
											stroke="#6b7280"
											strokeWidth="1.5"
										/>
										<path
											d="M7 9V6a3 3 0 116 0v3"
											stroke="#6b7280"
											strokeWidth="1.5"
											strokeLinecap="round"
										/>
									</svg>
								</div>
								<p className="text-sm font-medium mb-1">Connect your account</p>
								<p className="text-xs text-gray-700 mb-4">
									This server requires authentication.
								</p>
								<button
									className="px-5 py-2.5 bg-black text-white text-sm font-medium rounded-xl hover:bg-gray-800 transition-colors cursor-pointer"
									onClick={handleConnect}
								>
									Connect
								</button>
							</div>
						) : isLoading ? (
							<div className="text-sm text-gray-500 py-2">Loading tools...</div>
						) : tools && tools.length > 0 ? (
							<div className="space-y-2">
								{tools.map((tool) => (
									<AgentMCPTool
										key={tool.name}
										agent={agent}
										serverId={server.id}
										toolName={tool.name}
										toolDescription={tool.description}
										onUpdate={onUpdate}
									/>
								))}
							</div>
						) : (
							<div className="text-sm text-gray-500 py-2">
								No tools available
							</div>
						)}
					</div>
					<div className="flex w-full justify-center">
						<Button
							variant="ghost"
							size="sm"
							className="text-gray-500 cursor-pointer"
							onClick={() => handleToggleServer(server.id, false)}
						>
							Disable {server.name}
						</Button>
					</div>
				</div>
			)}
		</div>
	);
}

"use client";

import { MCPServer, OfficialMCPServer } from "@/types/mcp-servers";
import { Card, CardHeader } from "@/components/ui/card";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Plus, CheckIcon } from "lucide-react";
import { api } from "@/lib/api/client";
import { useMcpServersStore } from "@/stores/mcp-servers-store";

export interface MCPServerCardProps {
	server: MCPServer;
}

interface OfficialMCPServerCardProps {
	server: OfficialMCPServer;
	onInstall?: () => void;
	onClick?: () => void;
}

export default function MCPServerCard({ server }: MCPServerCardProps) {
	return (
		<Card className="border border-border/60 shadow-none rounded-md overflow-hidden group justify-center">
			<CardHeader className="gap-0">
				<div className="flex w-full min-w-0 items-center justify-between">
					<div className="flex w-full min-w-0 items-center gap-3">
						<Image
							src={
								server.iconUrl ??
								"https://storage.googleapis.com/choose-assets/mcp.png"
							}
							alt={server.name}
							width={40}
							height={40}
							className="shrink-0 rounded-md"
						/>

						<div className="min-w-0 flex-1">
							<h3 className="font-medium text-base truncate">{server.name}</h3>
							<p className="text-sm text-muted-foreground truncate">
								{server.url}
							</p>
						</div>
					</div>
				</div>
			</CardHeader>
			{/* {server.description && (
				<CardContent className="pt-0">
					<p className="text-xs text-muted-foreground line-clamp-2">
						{server.description}
					</p>
				</CardContent>
			)} */}
		</Card>
	);
}

export function OfficialMCPServerCard({
	server,
	onInstall,
	onClick,
}: OfficialMCPServerCardProps) {
	const { addMcpServer } = useMcpServersStore();

	// Check if this server requires credentials (non-DCR OAuth)
	const requiresCredentials =
		server.supportsDcr === false && server.authType === "oauth2";

	const handleInstall = () => {
		api
			.post("/mcp-servers", {
				name: server.name,
				url: server.url,
				authType: server.authType,
				iconUrl: server.iconUrl,
				description: server.description,
			})
			.then((response) => {
				// Add the newly installed server to the store
				addMcpServer(response.data);
				onInstall?.();
			})
			.catch(() => {
				console.error("Failed to install MCP server");
			});
	};

	const handleAddClick = () => {
		if (requiresCredentials && onClick) {
			onClick();
		} else {
			handleInstall();
		}
	};

	return (
		<Card className="border border-border/60 shadow-none rounded-md overflow-hidden group justify-center py-2">
			<CardHeader className="gap-0 px-4">
				<div className="flex w-full min-w-0 items-center justify-between">
					<div className="flex w-full min-w-0 items-center gap-3">
						<Image
							src={
								server.iconUrl ??
								"https://storage.googleapis.com/choose-assets/mcp.png"
							}
							alt={server.name}
							width={24}
							height={24}
							className="shrink-0 rounded-md"
						/>

						<div className="min-w-0 flex-1">
							<h3 className="text-sm font-medium truncate">{server.name}</h3>
						</div>
						{server.isInstalled ? (
							<Button variant="ghost" size="icon" className="cursor-pointer">
								<CheckIcon
									className="size-3 text-emerald-500"
									strokeWidth={3}
								/>
							</Button>
						) : (
							<Button
								variant="ghost"
								size="icon"
								className="cursor-pointer"
								onClick={handleAddClick}
							>
								<Plus className="w-4 h-4" />
							</Button>
						)}
					</div>
				</div>
			</CardHeader>
		</Card>
	);
}

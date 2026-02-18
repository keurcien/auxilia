"use client";

import { MCPServer } from "@/types/mcp-servers";
import { Card, CardHeader } from "@/components/ui/card";
import Image from "next/image";

export interface MCPServerCardProps {
	server: MCPServer;
	onClick?: () => void;
}

export default function MCPServerCard({ server, onClick }: MCPServerCardProps) {
	return (
		<Card
			className="border border-border/60 shadow-none rounded-md overflow-hidden group justify-center cursor-pointer hover:border-border transition-colors"
			onClick={onClick}
		>
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
		</Card>
	);
}

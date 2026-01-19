"use client";

import { Card, CardContent, CardHeader } from "@/components/ui/card";
import Image from "next/image";
import { MCPServerCardProps } from "./mcp-server-card";

export function OfficialMCPServerCard({ server }: MCPServerCardProps) {
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
							width={24}
							height={24}
							className="shrink-0 rounded-md"
						/>

						<div className="min-w-0 flex-1">
							<h3 className="font-medium text-base truncate">{server.name}</h3>
						</div>
					</div>
				</div>
			</CardHeader>
		</Card>
	);
}

"use client";

import { MCPServer } from "@/types/mcp-servers";
import Image from "next/image";

export interface MCPServerCardProps {
	server: MCPServer;
	onClick?: () => void;
}

export default function MCPServerCard({ server, onClick }: MCPServerCardProps) {
	return (
		<div
			className="group flex flex-col gap-4 p-7 rounded-3xl h-full bg-white dark:bg-card cursor-pointer transition-all duration-300"
			style={{ boxShadow: "0 2px 12px rgba(0,0,0,0.06)" }}
			onMouseEnter={(e) => {
				e.currentTarget.style.transform = "translateY(-6px) scale(1.02)";
				e.currentTarget.style.boxShadow =
					"0 20px 40px -12px rgba(0,0,0,0.08), 0 0 0 2px rgba(0,0,0,0.04)";
			}}
			onMouseLeave={(e) => {
				e.currentTarget.style.transform = "";
				e.currentTarget.style.boxShadow = "0 2px 12px rgba(0,0,0,0.06)";
			}}
			onClick={onClick}
		>
			<div className="flex items-center gap-3.5 min-w-0">
				<Image
					src={
						server.iconUrl ??
						"https://storage.googleapis.com/choose-assets/mcp.png"
					}
					alt={server.name}
					width={48}
					height={48}
					className="shrink-0 rounded-xl bg-muted transition-transform duration-300 group-hover:rotate-[-8deg] group-hover:scale-110"
				/>
				<div className="min-w-0">
					<h3 className="font-[family-name:var(--font-jakarta-sans)] text-[16px] font-bold text-[#1a1a2e] dark:text-foreground tracking-tight leading-tight truncate">
						{server.name}
					</h3>
					<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#999] dark:text-muted-foreground font-medium mt-0.5 truncate">
						{server.url}
					</p>
				</div>
			</div>
			<p className="font-[family-name:var(--font-dm-sans)] text-[14px] leading-relaxed text-[#666] dark:text-muted-foreground line-clamp-2 flex-1">
				{server.description || "No description provided."}
			</p>
		</div>
	);
}

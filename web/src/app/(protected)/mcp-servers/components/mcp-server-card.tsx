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
			className="group flex h-full flex-col rounded-[14px] border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card p-5 cursor-pointer transition-[border-color,box-shadow,transform] duration-[130ms] ease-out hover:-translate-y-px hover:border-[#cfe0d8] dark:hover:border-white/20 hover:shadow-[0_6px_18px_rgba(30,45,40,0.08)]"
			onClick={onClick}
		>
			{/* Head: logo tile · name / URL */}
			<div className="flex min-w-0 items-center gap-3.5">
				<span className="flex size-12 shrink-0 items-center justify-center overflow-hidden rounded-xl bg-white dark:bg-white/10 shadow-[0_2px_6px_rgba(30,45,40,0.14)]">
					<Image
						src={
							server.iconUrl ??
							"https://storage.googleapis.com/choose-assets/mcp.png"
						}
						alt={server.name}
						width={48}
						height={48}
						className="size-full object-cover"
					/>
				</span>
				<div className="min-w-0 flex-1">
					<div className="truncate font-[family-name:var(--font-jakarta-sans)] text-[16px] font-bold tracking-[-0.01em] text-[#1e2d28] dark:text-foreground">
						{server.name}
					</div>
					<div className="mt-0.5 truncate font-mono text-[11px] text-[#94a59d] dark:text-muted-foreground">
						{server.url}
					</div>
				</div>
			</div>

			{/* Description — 2-line clamp, reserves height so rows align */}
			<p className="mt-4 min-h-[44px] flex-1 font-[family-name:var(--font-dm-sans)] text-[13.5px] leading-relaxed text-[#5f7068] dark:text-muted-foreground line-clamp-2">
				{server.description || "No description provided."}
			</p>
		</div>
	);
}

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
			<div className="flex min-w-0 items-center gap-3">
				<span className="flex size-[42px] shrink-0 items-center justify-center overflow-hidden rounded-xl bg-white dark:bg-white/10 shadow-[0_2px_6px_rgba(30,45,40,0.14)]">
					<Image
						unoptimized
						src={
							server.iconUrl ??
							"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
						}
						alt={server.name}
						width={42}
						height={42}
						className="size-full object-cover"
					/>
				</span>
				<div className="min-w-0 flex-1">
					<div className="truncate font-[family-name:var(--font-jakarta-sans)] text-[15px] font-bold tracking-[-0.01em] text-[#1e2d28] dark:text-foreground">
						{server.name}
					</div>
					<div className="mt-px truncate font-mono text-[10.5px] text-[#94a59d] dark:text-muted-foreground">
						{server.url}
					</div>
				</div>
			</div>

			{/* Description — 2-line clamp, reserves height so rows align */}
			<p className="mt-4 min-h-[42px] flex-1 font-[family-name:var(--font-dm-sans)] text-[13px] leading-[1.55] text-[#5f7068] dark:text-muted-foreground line-clamp-2">
				{server.description || "No description provided."}
			</p>
		</div>
	);
}

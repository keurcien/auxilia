"use client";

import { useState, useMemo } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { ArrowRight, Pencil, X } from "lucide-react";
import { Agent, AgentPermission } from "@/types/agents";
import { agentColorBackground, agentPastel } from "@/lib/colors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import Image from "next/image";

interface AgentCardProps {
	agent: Agent;
}

const PERMISSION_HIERARCHY: Record<AgentPermission, number> = {
	member: 0,
	editor: 1,
	admin: 2,
	owner: 3,
};

const ROLE_BADGE_CONFIG: Record<
	AgentPermission,
	{ label: string; bg: string; text: string }
> = {
	owner: {
		label: "Owner",
		bg: "bg-[#e7f0eb] dark:bg-emerald-950",
		text: "text-[#3d8b63] dark:text-emerald-300",
	},
	admin: {
		label: "Admin",
		bg: "bg-[#e7f0eb] dark:bg-emerald-950",
		text: "text-[#3d8b63] dark:text-emerald-300",
	},
	editor: {
		label: "Editor",
		bg: "bg-[#f5edda] dark:bg-amber-950",
		text: "text-[#9a7b3c] dark:text-amber-300",
	},
	member: {
		label: "Member",
		bg: "bg-[#eef0ee] dark:bg-stone-800",
		text: "text-[#7d8077] dark:text-stone-400",
	},
};

function hasPermission(
	current: AgentPermission | null | undefined,
	required: AgentPermission,
): boolean {
	if (!current) return false;
	return PERMISSION_HIERARCHY[current] >= PERMISSION_HIERARCHY[required];
}

const NO_ACCESS_BADGE = {
	label: "No access",
	bg: "bg-[#F3E4E6] dark:bg-rose-950",
	text: "text-[#A35462] dark:text-rose-300",
};

export default function AgentCard({ agent }: AgentCardProps) {
	const router = useRouter();
	const [open, setOpen] = useState(false);
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const hasAccess = !!agent.currentUserPermission;

	const resolvedServers = useMemo(() => {
		if (!agent.mcpServers) return [];
		return agent.mcpServers.map((s) => {
			const full = mcpServers.find((m) => m.id === s.mcpServerId);
			return { id: s.mcpServerId, name: full?.name ?? s.mcpServerId, iconUrl: full?.iconUrl };
		});
	}, [agent.mcpServers, mcpServers]);

	const handleChat = () => {
		if (!hasPermission(agent.currentUserPermission, "member")) {
			alert("You don't have permission to chat with this agent.");
			return;
		}
		setOpen(false);
		router.push(`/agents/${agent.id}/chat`);
	};

	const handleEdit = () => {
		if (!hasPermission(agent.currentUserPermission, "editor")) {
			alert("You don't have permission to edit this agent.");
			return;
		}
		setOpen(false);
		router.push(`/agents/${agent.id}`);
	};

	const color = agent.color || "#9E9E9E";
	const pastel = agentPastel(color);

	return (
		<>
			<div
				className={`group flex h-full flex-col rounded-xl border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card p-4 pb-0 transition-[border-color,box-shadow] duration-[130ms] ease-out hover:border-[#cfe0d8] dark:hover:border-white/20 hover:shadow-[0_3px_10px_rgba(30,45,40,0.06)] ${
					hasAccess ? "cursor-pointer" : "cursor-default"
				}`}
				onClick={() => hasAccess && setOpen(true)}
			>
				{/* Head: tile · name/handle · role */}
				<div className="mb-2.5 flex min-w-0 items-center gap-[11px]">
					<span
						style={{ background: pastel.pill }}
						className="flex size-[38px] shrink-0 items-center justify-center rounded-[10px] text-[19px]"
					>
						{agent.emoji || "🤖"}
					</span>
					<div className="min-w-0 flex-1">
						<div className="truncate font-[family-name:var(--font-jakarta-sans)] text-[14.5px] font-bold tracking-[-0.01em] text-[#1e2d28] dark:text-foreground">
							{agent.name}
						</div>
						<div className="mt-px truncate font-mono text-[11px] text-[#94a59d] dark:text-muted-foreground">
							@{agent.name.toLowerCase().replace(/\s+/g, "_")}
						</div>
					</div>
					{(() => {
						const badge = agent.currentUserPermission
							? ROLE_BADGE_CONFIG[agent.currentUserPermission]
							: NO_ACCESS_BADGE;
						return (
							<span
								className={`ml-auto shrink-0 rounded-full px-[9px] py-[3px] text-[10.5px] font-semibold ${badge.bg} ${badge.text}`}
							>
								{badge.label}
							</span>
						);
					})()}
				</div>

				{/* Description — 2-line clamp, reserves height so rows align */}
				<p className="mb-3 min-h-[38px] flex-1 font-[family-name:var(--font-dm-sans)] text-[12.5px] leading-[1.5] text-[#5f7068] dark:text-muted-foreground line-clamp-2">
					{agent.description || "No description provided."}
				</p>

				{/* Meta — real MCP server icons */}
				{resolvedServers.length > 0 && (
					<div className="flex items-center border-t border-[#edf2ef] dark:border-white/5 py-2.5">
						<div className="flex items-center">
							{resolvedServers.map((server) => (
								<span
									key={server.id}
									title={server.name}
									className="-ml-1.5 flex size-5 items-center justify-center overflow-hidden rounded-full border border-[#e1ebe6] bg-surface first:ml-0 dark:border-white/10 dark:bg-white/5"
								>
									<Image
										src={
											server.iconUrl ??
											"https://storage.googleapis.com/choose-assets/mcp.png"
										}
										alt={server.name}
										width={20}
										height={20}
										className="size-full object-cover"
									/>
								</span>
							))}
						</div>
					</div>
				)}
			</div>

			{open && createPortal(
				<div
					className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(30,45,40,0.2)] backdrop-blur-[4px] animate-in fade-in duration-200"
					onClick={() => setOpen(false)}
				>
					<div
						className="bg-white dark:bg-card rounded-[28px] p-8 w-[440px] max-w-[90vw] shadow-[0_24px_48px_-12px_rgba(0,0,0,0.12)] animate-in slide-in-from-bottom-4 zoom-in-[0.97] duration-300"
						onClick={(e) => e.stopPropagation()}
					>
						{/* Avatar + Name + Close */}
						<div className="flex items-center gap-4 mb-6">
							<div
								style={{
									background: agentColorBackground(color),
									border: `1.5px solid ${color}18`,
								}}
								className="shrink-0 w-[60px] h-[60px] rounded-full flex items-center justify-center text-[30px]"
							>
								{agent.emoji || "🤖"}
							</div>
							<div className="flex-1 min-w-0">
								<div className="font-[family-name:var(--font-jakarta-sans)] text-[20px] font-extrabold text-[#1E2D28] dark:text-foreground tracking-[-0.02em] truncate">
									{agent.name}
								</div>
								<div className="font-[family-name:var(--font-dm-sans)] text-[13.5px] text-[#A3B5AD] dark:text-muted-foreground font-medium mt-0.5">
									@{agent.name.toLowerCase().replace(/\s+/g, "_")}
								</div>
							</div>
							<button
								onClick={() => setOpen(false)}
								className="shrink-0 self-start w-9 h-9 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15"
							>
								<X className="h-4 w-4 text-[#6B7F76]" />
							</button>
						</div>

						{/* Description */}
						<div className="mb-5">
							<div className="font-[family-name:var(--font-dm-sans)] text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em] mb-1.5">
								Description
							</div>
							<p className="font-[family-name:var(--font-dm-sans)] text-[14px] text-[#6B7F76] dark:text-muted-foreground leading-relaxed">
								{agent.description || "No description provided."}
							</p>
						</div>

						{/* Tools */}
						{resolvedServers.length > 0 && (
							<div className="mb-5">
								<div className="font-[family-name:var(--font-dm-sans)] text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em] mb-2.5">
									Tools
								</div>
								<div className="flex flex-wrap gap-2">
									{resolvedServers.map((server) => (
										<Image
											key={server.id}
											src={
												server.iconUrl ??
												"https://storage.googleapis.com/choose-assets/mcp.png"
											}
											alt={server.name}
											width={24}
											height={24}
											className="shrink-0 rounded-md"
										/>
									))}
								</div>
							</div>
						)}

						{/* Subagents */}
						{agent.subagents?.length > 0 && (
							<div className="mb-7">
								<div className="font-[family-name:var(--font-dm-sans)] text-[12px] font-semibold text-[#B8C8C0] dark:text-muted-foreground uppercase tracking-[0.06em] mb-2.5">
									Subagents
								</div>
								<div className="flex flex-wrap gap-2">
									{agent.subagents.map((sub) => (
										<div
											key={sub.id}
											className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-[#F5F8F6] dark:bg-white/5 font-[family-name:var(--font-dm-sans)] text-[13px] font-medium"
										>
											<span className="text-sm">{sub.emoji || "🤖"}</span>
											<span className="text-[#6B7F76] dark:text-muted-foreground">{sub.name}</span>
										</div>
									))}
								</div>
							</div>
						)}

						{/* Buttons */}
						<div className="flex gap-2.5">
							<button
								className="flex-1 flex items-center justify-center gap-2 py-3.5 rounded-full border-[1.5px] border-[#E0E8E4] dark:border-white/10 bg-white dark:bg-transparent font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-[#1E2D28] dark:text-foreground cursor-pointer transition-all hover:border-[#A3B5AD]"
								onClick={handleEdit}
							>
								<Pencil className="size-[15px] text-[#6B7F76]" />
								Edit
							</button>
							<button
								className="flex-1 flex items-center justify-center gap-2 py-3.5 rounded-full bg-[#111111] dark:bg-white font-[family-name:var(--font-dm-sans)] text-[14px] font-semibold text-white dark:text-[#111111] cursor-pointer shadow-[0_4px_12px_-2px_rgba(0,0,0,0.15)] transition-all hover:opacity-90"
								onClick={handleChat}
							>
								Chat
								<ArrowRight className="size-[15px]" />
							</button>
						</div>
					</div>
				</div>,
				document.body,
			)}
		</>
	);
}

"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, ListTree, Pencil, X } from "lucide-react";
import { Agent, AgentPermission } from "@/types/agents";
import { agentColorBackground, PASTEL_MAP } from "@/lib/colors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import Image from "next/image";

interface AgentCardProps {
	agent: Agent;
}

const PERMISSION_HIERARCHY: Record<AgentPermission, number> = {
	user: 0,
	editor: 1,
	admin: 2,
	owner: 3,
};

const ROLE_BADGE_CONFIG: Record<
	AgentPermission,
	{ label: string; bg: string; text: string; dot: string }
> = {
	owner: {
		label: "Owner",
		bg: "bg-[#E4EDE2] dark:bg-emerald-950",
		text: "text-[#4E7050] dark:text-emerald-300",
		dot: "bg-[#6B8F6B] dark:bg-emerald-400",
	},
	admin: {
		label: "Admin",
		bg: "bg-[#E4EDE2] dark:bg-emerald-950",
		text: "text-[#4E7050] dark:text-emerald-300",
		dot: "bg-[#6B8F6B] dark:bg-emerald-400",
	},
	editor: {
		label: "Editor",
		bg: "bg-[#F2EBDA] dark:bg-amber-950",
		text: "text-[#9A7B3C] dark:text-amber-300",
		dot: "bg-[#C4A04E] dark:bg-amber-400",
	},
	user: {
		label: "User",
		bg: "bg-[#EDEEE9] dark:bg-stone-800",
		text: "text-[#7D8077] dark:text-stone-400",
		dot: "bg-[#A3A79C] dark:bg-stone-500",
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
	dot: "bg-[#C97080] dark:bg-rose-400",
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
		if (!hasPermission(agent.currentUserPermission, "user")) {
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
	const pastel = PASTEL_MAP[color] || PASTEL_MAP["#9E9E9E"];

	return (
		<>
			<div
				className={`group flex flex-col gap-4 p-7 rounded-3xl h-full bg-white dark:bg-card transition-all duration-300 ${
					hasAccess ? "cursor-pointer" : "cursor-default"
				}`}
				style={{
					boxShadow: "0 2px 12px rgba(0,0,0,0.06)",
				}}
				onMouseEnter={(e) => {
					if (!hasAccess) return;
					e.currentTarget.style.transform = "translateY(-6px) scale(1.02)";
					e.currentTarget.style.boxShadow = `0 20px 40px -12px ${color}30, 0 0 0 2px ${color}20`;
				}}
				onMouseLeave={(e) => {
					e.currentTarget.style.transform = "";
					e.currentTarget.style.boxShadow = "0 2px 12px rgba(0,0,0,0.06)";
				}}
				onClick={() => hasAccess && setOpen(true)}
			>
				<div className="flex items-center gap-3.5 min-w-0">
					<div
						style={{
							background: agentColorBackground(color),
							border: `1.5px solid ${color}18`,
						}}
						className="flex items-center justify-center shrink-0 w-[52px] h-[52px] rounded-full text-[26px] transition-transform duration-300 group-hover:rotate-[-8deg] group-hover:scale-110"
					>
						{agent.emoji || "🤖"}
					</div>
					<div className="min-w-0">
						<h2 className="font-[family-name:var(--font-jakarta-sans)] text-[16px] font-bold text-[#1a1a2e] dark:text-foreground tracking-tight leading-tight truncate">
							{agent.name}
						</h2>
						<p className="font-[family-name:var(--font-dm-sans)] text-[13px] text-[#999] dark:text-muted-foreground font-medium mt-0.5">
							@{agent.name.toLowerCase().replace(/\s+/g, "_")}
						</p>
					</div>
				</div>
				<p className="font-[family-name:var(--font-dm-sans)] text-[14px] leading-relaxed text-[#666] dark:text-muted-foreground line-clamp-2 flex-1">
					{agent.description || "No description provided."}
				</p>
				<div className="flex items-center gap-2 flex-wrap mt-auto">
					{(() => {
						const badge = agent.currentUserPermission
							? ROLE_BADGE_CONFIG[agent.currentUserPermission]
							: NO_ACCESS_BADGE;
						return (
							<span
								className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium shrink-0 ${badge.bg} ${badge.text}`}
							>
								<span
									className={`w-1.5 h-1.5 rounded-full shrink-0 ${badge.dot}`}
								/>
								{badge.label}
							</span>
						);
					})()}
					{agent.subagents?.length > 0 && (
						<span
							style={{ background: pastel.pill, color: pastel.text }}
							className="font-[family-name:var(--font-dm-sans)] inline-flex items-center gap-1.5 px-3.5 py-1 rounded-full text-xs font-semibold"
						>
							<ListTree className="w-3.5 h-3.5" />
							{agent.subagents.length} subagent{agent.subagents.length > 1 ? "s" : ""}
						</span>
					)}
				</div>
			</div>

			{open && (
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
				</div>
			)}
		</>
	);
}

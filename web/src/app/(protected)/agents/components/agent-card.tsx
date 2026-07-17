"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { Agent, AgentPermission } from "@/types/agents";
import { agentPastel, agentColorBackground } from "@/lib/colors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import ArchivedAgentDialog from "@/app/(protected)/agents/components/archived-agent-dialog";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import Image from "next/image";

interface AgentCardProps {
	agent: Agent;
	// In the Archived view the card opens a restore/delete dialog instead of
	// navigating to the agent page, and only manage-capable users can open it.
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
}

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

const NO_ACCESS_BADGE = {
	label: "No access",
	bg: "bg-[#F3E4E6] dark:bg-rose-950",
	text: "text-[#A35462] dark:text-rose-300",
};

export default function AgentCard({
	agent,
	archived = false,
	onRemoved,
}: AgentCardProps) {
	const router = useRouter();
	const [open, setOpen] = useState(false);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	// Only the agent owner/admin (or workspace admin, which resolves to "admin")
	// may manage an archived agent.
	const canManage =
		agent.currentUserPermission === "owner" ||
		agent.currentUserPermission === "admin";
	const hasAccess = archived ? canManage : !!agent.currentUserPermission;

	const resolvedServers = useMemo(() => {
		if (!agent.mcpServers) return [];
		return agent.mcpServers.map((s) => {
			const full = mcpServers.find((m) => m.id === s.mcpServerId);
			return {
				id: s.mcpServerId,
				name: full?.name ?? s.mcpServerId,
				iconUrl: full?.iconUrl,
			};
		});
	}, [agent.mcpServers, mcpServers]);

	// Clicking a live card goes straight to the agent's detail page (read-only
	// for members; editing is gated there). Archived cards open the
	// restore/delete dialog instead. No access → explain via a dialog rather
	// than silently doing nothing.
	const handleClick = () => {
		if (!hasAccess) {
			setForbiddenOpen(true);
			return;
		}
		if (archived) {
			setOpen(true);
			return;
		}
		router.push(`/agents/${agent.id}`);
	};

	const color = agent.color || "#9E9E9E";
	const pastel = agentPastel(color);
	const ownerName = agent.owner?.name || agent.owner?.email;

	return (
		<>
			<div
				className="group flex h-full cursor-pointer flex-col rounded-xl border border-[#e1ebe6] dark:border-white/10 bg-white dark:bg-card p-4 pb-0 transition-[border-color,box-shadow] duration-[130ms] ease-out hover:border-[#cfe0d8] dark:hover:border-white/20 hover:shadow-[0_3px_10px_rgba(30,45,40,0.06)]"
				onClick={handleClick}
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
						{ownerName && (
							<div className="mt-px truncate text-[11px] text-[#94a59d] dark:text-muted-foreground">
								by {ownerName}
							</div>
						)}
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

				{/* Meta — MCP server icons (left) · subagents (right) */}
				{(resolvedServers.length > 0 || agent.subagents?.length > 0) && (
					<div className="flex items-center justify-between border-t border-[#edf2ef] dark:border-white/5 py-2.5">
						<div className="flex items-center">
							{resolvedServers.map((server) => (
								<span
									key={server.id}
									title={server.name}
									className="-ml-1.5 flex size-5 items-center justify-center overflow-hidden rounded-full border border-[#e1ebe6] bg-surface first:ml-0 dark:border-white/10 dark:bg-white/5"
								>
									<Image
										unoptimized
										src={
											server.iconUrl ??
											"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
										}
										alt={server.name}
										width={20}
										height={20}
										className="size-full object-cover"
									/>
								</span>
							))}
						</div>
						{agent.subagents?.length > 0 && (
							<div className="flex items-center">
								{agent.subagents.slice(0, 4).map((sub) => (
									<span
										key={sub.id}
										title={sub.name}
										style={
											sub.color
												? {
														background: agentColorBackground(sub.color),
														border: `1px solid ${sub.color}18`,
													}
												: undefined
										}
										className="-ml-1.5 flex size-5 items-center justify-center rounded-full border border-[#e1ebe6] bg-surface text-[13px] leading-none first:ml-0 dark:border-white/10 dark:bg-white/5"
									>
										{sub.emoji || "🤖"}
									</span>
								))}
								{agent.subagents.length > 4 && (
									<span
										title={agent.subagents
											.slice(4)
											.map((s) => s.name)
											.join(", ")}
										className="-ml-1.5 flex size-5 items-center justify-center rounded-full border border-[#e1ebe6] bg-surface text-[9px] font-semibold text-[#7d8077] first:ml-0 dark:border-white/10 dark:bg-white/5 dark:text-muted-foreground"
									>
										+{agent.subagents.length - 4}
									</span>
								)}
							</div>
						)}
					</div>
				)}
			</div>

			{open && archived && (
				<ArchivedAgentDialog
					agent={agent}
					onClose={() => {
						setOpen(false);
					}}
					onRemoved={(id) => onRemoved?.(id)}
				/>
			)}

			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={setForbiddenOpen}
				title="No access"
				message="You don't have permission to view this agent. Ask the agent's owner or a workspace admin to grant you access."
			/>
		</>
	);
}

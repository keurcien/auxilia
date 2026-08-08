"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Agent, AgentPermission } from "@/types/agents";
import { agentPastel, agentColorBackground } from "@/lib/colors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import ArchivedAgentDialog from "@/app/(protected)/agents/components/archived-agent-dialog";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 8;
const MAX_INLINE_AVATARS = 4;

// Grid shared by the header row and body rows (design 7a).
const ROW_GRID =
	"grid grid-cols-[minmax(0,1.5fr)_140px_110px_170px_100px_24px] items-center gap-4";

const ROLE_BADGES: Record<AgentPermission, { label: string; className: string }> = {
	owner: { label: "OWNER", className: "bg-success-bg text-success" },
	admin: { label: "ADMIN", className: "bg-success-bg text-success" },
	editor: { label: "EDITOR", className: "bg-warning-bg text-warning" },
	member: {
		label: "MEMBER",
		className: "bg-neutral-bg text-meta dark:bg-white/10 dark:text-panel-dim",
	},
};

const NO_ACCESS_BADGE = {
	label: "NO ACCESS",
	className: "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/10",
};

function ownerInitials(name: string): string {
	const parts = name.trim().split(/\s+/);
	if (parts.length >= 2) {
		return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
	}
	return name.slice(0, 2).toUpperCase();
}

interface AgentTableProps {
	agents: Agent[];
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
}

/** Design 7a agents table: bordered container, teal mono names, favicon and
 * subagent chips, owner, role badge, mono pagination footer. */
export default function AgentTable({
	agents,
	archived = false,
	onRemoved,
}: AgentTableProps) {
	const router = useRouter();
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const [page, setPage] = useState(0);
	const [archivedAgent, setArchivedAgent] = useState<Agent | null>(null);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	const pageCount = Math.max(1, Math.ceil(agents.length / PAGE_SIZE));
	const currentPage = Math.min(page, pageCount - 1);
	const start = currentPage * PAGE_SIZE;
	const rows = useMemo(
		() => agents.slice(start, start + PAGE_SIZE),
		[agents, start],
	);

	const serverInfo = (serverId: string) => {
		const full = mcpServers.find((m) => m.id === serverId);
		return { name: full?.name ?? serverId, iconUrl: full?.iconUrl };
	};

	const handleRowClick = (agent: Agent) => {
		const canManage =
			agent.currentUserPermission === "owner" ||
			agent.currentUserPermission === "admin";
		const hasAccess = archived ? canManage : !!agent.currentUserPermission;
		if (!hasAccess) {
			setForbiddenOpen(true);
			return;
		}
		if (archived) {
			setArchivedAgent(agent);
			return;
		}
		router.push(`/agents/${agent.id}`);
	};

	return (
		<div className="w-full overflow-x-auto [scrollbar-width:thin]">
			<div className="min-w-[760px]">
				{/* Column headers */}
				<div
					className={cn(
						ROW_GRID,
						"px-4 pb-2 pt-1 font-mono text-[10px] font-semibold tracking-[0.09em] text-meta dark:text-panel-dim",
					)}
				>
					<span>AGENT</span>
					<span>MCP SERVERS</span>
					<span>SUBAGENTS</span>
					<span>OWNER</span>
					<span>ACCESS</span>
					<span />
				</div>

				{/* Rows */}
				<div className="overflow-hidden rounded-[10px] border border-border">
					{rows.map((agent) => {
						const pastel = agentPastel(agent.color || "#9E9E9E");
						const ownerName =
							agent.owner?.name || agent.owner?.email || "Unknown";
						const badge = agent.currentUserPermission
							? ROLE_BADGES[agent.currentUserPermission]
							: NO_ACCESS_BADGE;
						const servers = (agent.mcpServers ?? []).map((s) =>
							serverInfo(s.mcpServerId),
						);
						const subagents = agent.subagents ?? [];

						return (
							<div
								key={agent.id}
								onClick={() => {
									handleRowClick(agent);
								}}
								className={cn(
									ROW_GRID,
									"cursor-pointer border-b border-hover bg-card px-4 py-3 transition-colors last:border-b-0 hover:bg-sidebar dark:border-white/5",
								)}
							>
								{/* Agent */}
								<span className="flex min-w-0 items-center gap-3">
									<span
										style={{ background: pastel.pill }}
										className="flex size-8 shrink-0 items-center justify-center rounded-lg text-base"
									>
										{agent.emoji || "🤖"}
									</span>
									<span className="min-w-0">
										<span className="block truncate font-mono text-[12.5px] font-semibold tracking-[-0.01em] text-petrol">
											{agent.name}
										</span>
										<span className="mt-0.5 block truncate text-xs text-muted-foreground">
											{agent.description || "No description provided."}
										</span>
									</span>
								</span>

								{/* MCP servers */}
								<span className="flex gap-1.5">
									{servers.slice(0, MAX_INLINE_AVATARS).map((server, i) => (
										<span
											key={`${server.name}-${i}`}
											title={server.name}
											className="flex size-6 shrink-0 items-center justify-center rounded-[6px] border border-border bg-card"
										>
											<Image
												unoptimized
												width={14}
												height={14}
												src={
													server.iconUrl ??
													"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
												}
												alt={server.name}
												className="rounded-[2px] object-contain"
											/>
										</span>
									))}
									{servers.length > MAX_INLINE_AVATARS && (
										<span
											title={servers
												.slice(MAX_INLINE_AVATARS)
												.map((s) => s.name)
												.join(", ")}
											className="flex size-6 shrink-0 items-center justify-center rounded-[6px] border border-border bg-card font-mono text-[9px] font-semibold text-meta"
										>
											+{servers.length - MAX_INLINE_AVATARS}
										</span>
									)}
								</span>

								{/* Subagents */}
								<span className="flex gap-1">
									{subagents.slice(0, MAX_INLINE_AVATARS).map((sub) => (
										<span
											key={sub.id}
											title={sub.name}
											style={
												sub.color
													? { background: agentColorBackground(sub.color) }
													: undefined
											}
											className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-[rgba(16,24,32,0.06)] bg-hover text-[11px]"
										>
											{sub.emoji || "🤖"}
										</span>
									))}
									{subagents.length > MAX_INLINE_AVATARS && (
										<span
											title={subagents
												.slice(MAX_INLINE_AVATARS)
												.map((s) => s.name)
												.join(", ")}
											className="flex size-[22px] shrink-0 items-center justify-center rounded-full border border-[rgba(16,24,32,0.06)] bg-hover font-mono text-[9px] font-semibold text-meta"
										>
											+{subagents.length - MAX_INLINE_AVATARS}
										</span>
									)}
								</span>

								{/* Owner */}
								<span className="flex min-w-0 items-center gap-2">
									<span className="flex size-[22px] shrink-0 items-center justify-center rounded-full bg-primary text-[8.5px] font-bold text-primary-foreground">
										{ownerInitials(ownerName)}
									</span>
									<span className="truncate text-[12.5px] text-body dark:text-panel-body">
										{ownerName}
									</span>
								</span>

								{/* Access */}
								<span>
									<span
										className={cn(
											"rounded-[4px] px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em]",
											badge.className,
										)}
									>
										{badge.label}
									</span>
								</span>

								<span className="text-right text-ghost">›</span>
							</div>
						);
					})}
				</div>

				{/* Footer: count + pagination */}
				<div className="flex items-center justify-between px-1 py-3.5">
					<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
						{agents.length === 0
							? "0 agents"
							: `${start + 1}–${Math.min(start + PAGE_SIZE, agents.length)} of ${agents.length} agent${agents.length === 1 ? "" : "s"}`}
					</span>
					{pageCount > 1 && (
						<span className="flex items-center gap-1">
							<button
								type="button"
								aria-label="Previous page"
								disabled={currentPage === 0}
								onClick={() => {
									setPage(currentPage - 1);
								}}
								className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] border border-border text-subtle transition-colors hover:bg-sidebar disabled:cursor-default disabled:border-hover disabled:text-ghost dark:disabled:border-white/5"
							>
								<ChevronLeft className="size-3.5" />
							</button>
							{Array.from({ length: pageCount }, (_, i) => (
								<button
									key={i}
									type="button"
									onClick={() => {
										setPage(i);
									}}
									className={cn(
										"flex size-7 cursor-pointer items-center justify-center rounded-[7px] font-mono text-[11.5px] transition-colors",
										i === currentPage
											? "bg-petrol font-semibold text-white"
											: "border border-border font-medium text-subtle hover:bg-sidebar dark:text-panel-body",
									)}
								>
									{i + 1}
								</button>
							))}
							<button
								type="button"
								aria-label="Next page"
								disabled={currentPage >= pageCount - 1}
								onClick={() => {
									setPage(currentPage + 1);
								}}
								className="flex size-7 cursor-pointer items-center justify-center rounded-[7px] border border-border text-subtle transition-colors hover:bg-sidebar disabled:cursor-default disabled:border-hover disabled:text-ghost dark:disabled:border-white/5"
							>
								<ChevronRight className="size-3.5" />
							</button>
						</span>
					)}
				</div>
			</div>

			{archivedAgent && archived && (
				<ArchivedAgentDialog
					agent={archivedAgent}
					onClose={() => {
						setArchivedAgent(null);
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
		</div>
	);
}

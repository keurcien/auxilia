"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Agent, AgentPermission } from "@/types/agents";
import { agentPastel, agentColorBackground } from "@/lib/colors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import ArchivedAgentDialog from "@/app/(protected)/agents/components/archived-agent-dialog";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { UserAvatar } from "@/components/ui/user-avatar";
import { cn } from "@/lib/utils";

const MAX_INLINE_AVATARS = 3;

// Agents with no tag are collected under this trailing pseudo-group
// (mirrors the card grid's tag sections).
const NO_TAG_ID = "__none__";

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

interface AgentTableProps {
	agents: Agent[];
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
}

/** Design 7a agents table on the shared DataTable: teal mono names, favicon
 * and subagent chips, owner, role badge, tag-grouped subheaders; the body
 * caps at the page height and scrolls internally. */
export default function AgentTable({
	agents,
	archived = false,
	onRemoved,
}: AgentTableProps) {
	const router = useRouter();
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const [archivedAgent, setArchivedAgent] = useState<Agent | null>(null);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	// Group by tag like the card grid: tags alphabetically, untagged agents
	// under a trailing "Others" group. Rows are flattened in group order so
	// the table's subheaders line up with pagination slices.
	const { orderedAgents, groupMeta } = useMemo(() => {
		const byTag = new Map<string, { label: string; items: Agent[] }>();
		const untagged: Agent[] = [];
		for (const agent of agents) {
			if (!agent.tag) {
				untagged.push(agent);
				continue;
			}
			const existing = byTag.get(agent.tag.id);
			if (existing) existing.items.push(agent);
			else byTag.set(agent.tag.id, { label: agent.tag.name, items: [agent] });
		}
		const ordered = [...byTag.entries()].sort(([, a], [, b]) =>
			a.label.localeCompare(b.label),
		);
		if (untagged.length > 0) {
			ordered.push([NO_TAG_ID, { label: "Others", items: untagged }]);
		}
		return {
			orderedAgents: ordered.flatMap(([, group]) => group.items),
			groupMeta: new Map(
				ordered.map(([id, group]) => [
					id,
					{ label: group.label, count: group.items.length },
				]),
			),
		};
	}, [agents]);

	// A lone "Others" group means tags aren't in use — headers would be noise.
	const showGroups = !(groupMeta.size === 1 && groupMeta.has(NO_TAG_ID));

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

	const columns: DataTableColumn<Agent>[] = [
		{
			key: "agent",
			header: "Agent",
			width: "minmax(0, 1.5fr)",
			cell: (agent) => {
				const pastel = agentPastel(agent.color || "#9E9E9E");
				return (
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
				);
			},
		},
		{
			key: "mcpServers",
			header: "MCP servers",
			width: "140px",
			hideBelowMd: true,
			cell: (agent) => {
				const servers = (agent.mcpServers ?? []).map((s) =>
					serverInfo(s.mcpServerId),
				);
				return (
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
				);
			},
		},
		{
			key: "subagents",
			header: "Subagents",
			width: "110px",
			hideBelowMd: true,
			cell: (agent) => {
				const subagents = agent.subagents ?? [];
				return (
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
				);
			},
		},
		{
			key: "owner",
			header: "Owner",
			width: "170px",
			hideBelowMd: true,
			cell: (agent) => {
				const ownerName = agent.owner?.name || agent.owner?.email || "Unknown";
				return (
					<span className="flex min-w-0 items-center gap-2">
						<UserAvatar
							name={ownerName}
							pictureUrl={agent.owner?.pictureUrl}
							className="size-[22px] shrink-0"
							fallbackClassName="bg-primary text-[8.5px] text-primary-foreground dark:bg-primary"
						/>
						<span className="truncate text-[12.5px] text-body dark:text-panel-body">
							{ownerName}
						</span>
					</span>
				);
			},
		},
		{
			key: "access",
			header: "Access",
			width: "100px",
			mobileWidth: "auto",
			cell: (agent) => {
				const badge = agent.currentUserPermission
					? ROLE_BADGES[agent.currentUserPermission]
					: NO_ACCESS_BADGE;
				return (
					<span
						className={cn(
							"rounded-[4px] px-2 py-0.5 font-mono text-[9.5px] font-semibold tracking-[0.05em]",
							badge.className,
						)}
					>
						{badge.label}
					</span>
				);
			},
		},
		{
			key: "chevron",
			header: "",
			width: "24px",
			mobileWidth: "auto",
			align: "right",
			cell: () => <span className="text-ghost">›</span>,
		},
	];

	return (
		<>
			<DataTable
				columns={columns}
				rows={orderedAgents}
				rowKey={(agent) => agent.id}
				onRowClick={handleRowClick}
				emptyMessage="No agents here."
				scrollBody
				groupBy={
					showGroups
						? {
								key: (agent) => agent.tag?.id ?? NO_TAG_ID,
								header: (key) => {
									const group = groupMeta.get(key);
									return (
										<>
											<span className="font-mono text-[10px] font-semibold uppercase tracking-[0.09em] text-subtle dark:text-panel-dim">
												{group?.label}
											</span>
											<span className="ml-2 font-mono text-[10.5px] text-meta dark:text-panel-dim">
												{group?.count}
											</span>
										</>
									);
								},
							}
						: undefined
				}
			/>

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
		</>
	);
}

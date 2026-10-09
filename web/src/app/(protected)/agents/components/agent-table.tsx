"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Agent, AgentPermission } from "@/types/agents";
import { agentColorBackground } from "@/lib/colors";
import { useMcpServersStore } from "@/stores/mcp-servers-store";
import ArchivedAgentDialog from "@/app/(protected)/agents/components/archived-agent-dialog";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { Checkbox } from "@/components/ui/checkbox";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import { UserAvatar } from "@/components/ui/user-avatar";
import { cn } from "@/lib/utils";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { VisibilityBadge } from "@/components/ui/visibility-badge";
import { mcpServerImageUrl } from "@/lib/api/resources/mcp-servers";
import { buildGroupTree } from "@/lib/groups";

const MAX_INLINE_AVATARS = 3;

const ROLE_BADGES: Record<AgentPermission, { label: string; className: string }> = {
	owner: { label: "Owner", className: "bg-success-bg text-success" },
	admin: { label: "Admin", className: "bg-success-bg text-success" },
	editor: { label: "Editor", className: "bg-warning-bg text-warning" },
	member: {
		label: "Member",
		className: "bg-neutral-bg text-meta dark:bg-white/10 dark:text-panel-dim",
	},
};

const NO_ACCESS_BADGE = {
	label: "No access",
	className: "bg-[#FBEFED] text-[#B04A3A] dark:bg-[#B04A3A]/10",
};

interface AgentTableProps {
	agents: Agent[];
	archived?: boolean;
	onRemoved?: (agentId: string) => void;
	selectedIds: Set<string>;
	selectionMode: boolean;
	onToggleAll: () => void;
	onToggleSelection: (agentId: string, shiftKey: boolean) => void;
}

/** Agents table with slash-delimited, collapsible group rows. */
export default function AgentTable({
	agents,
	archived = false,
	onRemoved,
	selectedIds,
	selectionMode,
	onToggleAll,
	onToggleSelection,
}: AgentTableProps) {
	const router = useRouter();
	const mcpServers = useMcpServersStore((state) => state.mcpServers);
	const [archivedAgent, setArchivedAgent] = useState<Agent | null>(null);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	const groupTree = useMemo(() => buildGroupTree(agents), [agents]);
	const hasSelectableAgents = agents.some(
		(agent) =>
			agent.currentUserPermission === "owner" ||
			agent.currentUserPermission === "admin",
	);

	const serverInfo = (serverId: string) => {
		const full = mcpServers.find((m) => m.id === serverId);
		return {
			id: serverId,
			name: full?.name ?? serverId,
			iconUrl: full?.iconUrl,
			imageRevision: full?.imageRevision,
		};
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
			header: selectionMode ? (
				""
			) : (
				<span className="flex items-center gap-3">
					<Checkbox
						checked={false}
						aria-label="Select all agents"
						disabled={!hasSelectableAgents}
						onCheckedChange={onToggleAll}
					/>
					<button
						type="button"
						disabled={!hasSelectableAgents}
						onClick={onToggleAll}
						className="cursor-pointer text-[12px]! font-semibold text-foreground hover:text-petrol disabled:cursor-not-allowed disabled:opacity-50"
					>
						Select all
					</button>
				</span>
			),
			width: "minmax(220px, 1.5fr)",
			cell: (agent) => {
				return (
					<span className="flex min-w-0 items-center gap-3">
						<SelectableLeading
							selected={selectedIds.has(agent.id)}
							selectionMode={selectionMode}
							disabled={
								agent.currentUserPermission !== "owner" &&
								agent.currentUserPermission !== "admin"
							}
							label={`Select ${agent.name}`}
							onToggle={(shiftKey) => {
								onToggleSelection(agent.id, shiftKey);
							}}
							className="size-6"
						>
							<AgentAvatar
								agentId={agent.id}
								name={agent.name}
								imageRevision={agent.imageRevision}
								color={agent.color}
								emoji={agent.emoji}
								size="xs"
							/>
						</SelectableLeading>
						<span className="min-w-0">
							<span className="block truncate text-[12.5px] font-semibold tracking-[-0.01em] text-petrol">
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
								className="flex size-6 shrink-0 items-center justify-center overflow-hidden rounded-[6px] border border-border bg-card"
							>
								{/* eslint-disable-next-line @next/next/no-img-element */}
								<img
									width={20}
									height={20}
									src={
										(server.imageRevision
											? mcpServerImageUrl(server.id, server.imageRevision)
											: server.iconUrl) ??
										"https://pub-7a6e8912b3c448b8a8bfa47a0363f7bc.r2.dev/assets/icons/mcp.png"
									}
									alt={server.name}
									className="size-5 rounded-[4px] object-cover"
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
			key: "visibility",
			header: "Visibility",
			width: "120px",
			cell: (agent) => <VisibilityBadge visibility={agent.visibility} />,
		},
		{
			key: "owner",
			header: "Owner",
			width: "170px",
			cell: (agent) => {
				const ownerName = agent.owner?.name || agent.owner?.email || "Unknown";
				return (
					<span className="flex min-w-0 items-center gap-2">
						<UserAvatar
							name={ownerName}
							pictureUrl={agent.owner?.pictureUrl}
							userId={agent.owner?.id}
							imageRevision={agent.owner?.imageRevision}
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
							"rounded-[4px] px-2 py-0.5 text-[9.5px] font-semibold ",
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
				rows={agents}
				rowKey={(agent) => agent.id}
				isRowSelected={(agent) => selectedIds.has(agent.id)}
				selectionMode={selectionMode}
				isRowSelectable={(agent) =>
					agent.currentUserPermission === "owner" ||
					agent.currentUserPermission === "admin"
				}
				onRowSelectionClick={(agent, shiftKey) => {
					onToggleSelection(agent.id, shiftKey);
				}}
				onRowClick={handleRowClick}
				emptyMessage="No agents here."
				scrollBody
				minTableWidth="1020px"
				bleedOnNarrow
				groupTree={{
					...groupTree,
					storageKey: "agents:table-group",
				}}
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

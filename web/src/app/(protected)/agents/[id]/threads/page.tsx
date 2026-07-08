"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { api } from "@/lib/api/client";
import { PageContainer } from "@/components/layout/page-container";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { ThreadSourceBadge } from "@/components/ui/thread-source-badge";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import type { Agent } from "@/types/agents";
import type { Paginated } from "@/types/api";
import type { AgentThread } from "@/types/threads";

const PAGE_SIZE = 10;

function initials(name: string | null, email: string | null): string {
	const source = name || email || "?";
	const parts = source.trim().split(/\s+/);
	if (parts.length >= 2) {
		return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
	}
	return source.substring(0, 2).toUpperCase();
}

function formatDate(dateStr: string): string {
	const diff = Date.now() - new Date(dateStr).getTime();
	const minutes = Math.floor(diff / (1000 * 60));
	if (minutes < 1) return "just now";
	if (minutes < 60) return `${minutes}m ago`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h ago`;
	const days = Math.floor(hours / 24);
	if (days < 7) return `${days}d ago`;
	return new Date(dateStr).toLocaleDateString("en-US", {
		month: "short",
		day: "numeric",
		year: "numeric",
	});
}

export default function AgentThreadsPage() {
	const params = useParams();
	const router = useRouter();
	const agentId = params.id as string;
	const [agent, setAgent] = useState<Agent | null>(null);
	const [threads, setThreads] = useState<AgentThread[]>([]);
	const [total, setTotal] = useState(0);
	const [offset, setOffset] = useState(0);
	const [isLoading, setIsLoading] = useState(true);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);
	const [hasError, setHasError] = useState(false);

	useEffect(() => {
		const fetch = async () => {
			setIsLoading(true);
			try {
				const [agentRes, threadsRes] = await Promise.all([
					api.get<Agent>(`/agents/${agentId}`),
					api.get<Paginated<AgentThread>>(`/agents/${agentId}/threads`, {
						params: { limit: PAGE_SIZE, offset },
					}),
				]);
				setAgent(agentRes.data);
				setThreads(threadsRes.data.items);
				setTotal(threadsRes.data.total);
			} catch (error: unknown) {
				if (
					error instanceof Object &&
					"status" in error &&
					(error.status === 403 || error.status === 401)
				) {
					setForbiddenOpen(true);
				} else {
					console.error("Error fetching agent threads:", error);
					setHasError(true);
				}
			} finally {
				setIsLoading(false);
			}
		};
		void fetch();
	}, [agentId, offset]);

	const columns: DataTableColumn<AgentThread>[] = [
		{
			key: "firstMessage",
			header: "First message",
			width: "1fr",
			cell: (thread) => (
				<span className="block truncate font-[family-name:var(--font-dm-sans)] text-[13.5px] font-medium text-[#3F524B] dark:text-foreground/80">
					{thread.firstMessageContent || (
						<span className="italic text-[#A3B5AD]">No message</span>
					)}
				</span>
			),
		},
		{
			key: "user",
			header: "User",
			width: "220px",
			hideBelowMd: true,
			cell: (thread) => (
				<div className="flex min-w-0 items-center gap-2.5">
					<span className="flex size-[26px] shrink-0 items-center justify-center rounded-full bg-[#e7f0eb] font-[family-name:var(--font-jakarta-sans)] text-[10px] font-bold text-[#3d8b63] dark:bg-emerald-950 dark:text-emerald-300">
						{initials(thread.userName, thread.userEmail)}
					</span>
					<span className="truncate font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#5f7068] dark:text-muted-foreground">
						{thread.userName || thread.userEmail || "Unknown"}
					</span>
				</div>
			),
		},
		{
			key: "source",
			header: "Source",
			width: "110px",
			mobileWidth: "auto",
			cell: (thread) => <ThreadSourceBadge source={thread.source} />,
		},
		{
			key: "created",
			header: "Created",
			width: "110px",
			mobileWidth: "auto",
			align: "right",
			cell: (thread) => (
				<span className="font-[family-name:var(--font-dm-sans)] text-[13px] font-medium text-[#8FA89E] dark:text-muted-foreground">
					{formatDate(thread.createdAt)}
				</span>
			),
		},
	];

	return (
		<PageContainer>
			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={(open) => {
					setForbiddenOpen(open);
					if (!open) router.push(`/agents/${agentId}`);
				}}
				title="Insufficient privileges"
				message="You don't have permission to view this agent's threads."
			/>

			<div className="flex items-start gap-4 my-8">
				<button
					type="button"
					onClick={() => {
						router.push(`/agents/${agentId}`);
					}}
					className="shrink-0 w-10 h-10 rounded-full bg-[#F5F8F6] dark:bg-white/10 flex items-center justify-center cursor-pointer transition-colors hover:bg-[#EDF4F0] dark:hover:bg-white/15"
					aria-label="Back to agent"
				>
					<ArrowLeft className="w-[18px] h-[18px] text-[#6B7F76]" />
				</button>

				<div className="flex-1 min-w-0">
					<div className="mb-7 flex items-center justify-between gap-4">
						<h1 className="font-[family-name:var(--font-jakarta-sans)] font-extrabold text-[28px] tracking-[-0.03em] text-[#111111] dark:text-white truncate">
							Thread history
						</h1>
						{agent && (
							<div className="flex items-center gap-2 shrink-0 min-w-0">
								<AgentAvatar
									color={agent.color}
									emoji={agent.emoji}
									size="sm"
								/>
								<h2 className="text-md font-bold truncate">{agent.name}</h2>
							</div>
						)}
					</div>

					{hasError ? (
						<div className="text-center py-16 text-[14px] text-[#A3B5AD] dark:text-muted-foreground font-medium">
							Failed to load threads. Please try again.
						</div>
					) : (
						<DataTable
							columns={columns}
							rows={threads}
							rowKey={(thread) => thread.id}
							isLoading={isLoading}
							emptyMessage="No threads yet for this agent."
							getRowHref={(thread) => `/agents/${agentId}/chat/${thread.id}`}
							pagination={{
								total,
								limit: PAGE_SIZE,
								offset,
								onOffsetChange: setOffset,
							}}
						/>
					)}
				</div>
			</div>
		</PageContainer>
	);
}

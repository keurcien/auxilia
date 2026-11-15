"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { RotateCcw } from "lucide-react";
import ForbiddenErrorDialog from "@/components/forbidden-error-dialog";
import { WorkspacePage } from "@/components/layout/workspace-page";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { ThreadSourceBadge } from "@/components/ui/thread-source-badge";
import { UserAvatar } from "@/components/ui/user-avatar";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as agentsApi from "@/lib/api/resources/agents";
import * as threadsApi from "@/lib/api/resources/threads";
import { useWorkspaceEventsStore } from "@/stores/workspace-events-store";
import type { Agent } from "@/types/agents";
import type { AgentThread } from "@/types/threads";

const PAGE_SIZE = 20;

function isAccessDenied(error: unknown): boolean {
	return (
		error instanceof Object &&
		"status" in error &&
		(error.status === 403 || error.status === 401)
	);
}

function threadTitle(thread: AgentThread): string {
	return thread.firstMessageContent?.trim() || "Untitled conversation";
}

function threadAuthor(thread: AgentThread): string {
	return thread.userName || thread.userEmail || "Unknown user";
}

function formatDate(value: string): string {
	return new Date(value)
		.toLocaleDateString("en-US", {
			year: "numeric",
			month: "short",
			day: "numeric",
		})
		.toLowerCase();
}

function formatDateTime(value: string): string {
	return new Date(value).toLocaleString("en-US", {
		dateStyle: "medium",
		timeStyle: "short",
	});
}

/**
 * Every user's conversations with one agent, newest first. The endpoint is
 * restricted to the agent's owner and admins and only pages, so the list is
 * read-only: opening a row is the one action.
 */
export default function AgentThreadsPage() {
	const params = useParams();
	const router = useRouter();
	const agentId = params.id as string;
	const threadsVersion = useWorkspaceEventsStore(
		(state) => state.threadsVersion,
	);
	const [agent, setAgent] = useState<Agent | null>(null);
	const [threads, setThreads] = useState<AgentThread[]>([]);
	const [total, setTotal] = useState(0);
	const [offsetParam, setOffsetParam] = useQueryParamState("offset");
	const parsedOffset = Number.parseInt(offsetParam, 10);
	const offset =
		Number.isFinite(parsedOffset) && parsedOffset >= 0 ? parsedOffset : 0;
	const [reloadVersion, setReloadVersion] = useState(0);
	const requestKey = [agentId, offset, threadsVersion, reloadVersion].join(":");
	const [settledRequestKey, setSettledRequestKey] = useState<string | null>(
		null,
	);
	const isLoading = settledRequestKey !== requestKey;
	const [loadError, setLoadError] = useState<string | null>(null);
	const [forbiddenOpen, setForbiddenOpen] = useState(false);

	useEffect(() => {
		let cancelled = false;
		void agentsApi
			.getAgent(agentId)
			.then((result) => {
				if (!cancelled) setAgent(result);
			})
			.catch((error: unknown) => {
				if (!cancelled && isAccessDenied(error)) setForbiddenOpen(true);
			});
		return () => {
			cancelled = true;
		};
	}, [agentId]);

	useEffect(() => {
		let cancelled = false;
		void threadsApi
			.listAgentThreads(agentId, { limit: PAGE_SIZE, offset })
			.then((page) => {
				if (cancelled) return;
				setThreads(page.items);
				setTotal(page.total);
				setLoadError(null);
			})
			.catch((error: unknown) => {
				if (cancelled) return;
				if (isAccessDenied(error)) {
					setForbiddenOpen(true);
					return;
				}
				setLoadError(getApiErrorMessage(error, "Could not load conversations."));
			})
			.finally(() => {
				if (!cancelled) setSettledRequestKey(requestKey);
			});
		return () => {
			cancelled = true;
		};
	}, [agentId, offset, requestKey]);

	const changePage = (nextOffset: number) => {
		setOffsetParam(nextOffset > 0 ? String(nextOffset) : "");
		const scrollArea = document.querySelector("[data-workspace-scroll]");
		if (scrollArea) scrollArea.scrollTop = 0;
	};

	const columns: DataTableColumn<AgentThread>[] = [
		{
			key: "conversation",
			header: "Conversation",
			width: "minmax(0, 2fr)",
			mobileWidth: "minmax(0, 1fr)",
			cell: (thread) => (
				<div className="min-w-0">
					<p
						title={threadTitle(thread)}
						className="line-clamp-2 break-words text-[12.5px] font-semibold text-foreground lg:line-clamp-1"
					>
						{threadTitle(thread)}
					</p>
					<div className="mt-1 flex min-w-0 items-center gap-2 lg:hidden">
						<span className="min-w-0 truncate text-[11.5px] text-meta dark:text-panel-dim">
							{threadAuthor(thread)}
						</span>
						<ThreadSourceBadge source={thread.source} />
					</div>
				</div>
			),
		},
		{
			key: "user",
			header: "User",
			width: "minmax(0, 1fr)",
			hideBelowLg: true,
			cell: (thread) => (
				<div className="flex min-w-0 items-center gap-2.5">
					<UserAvatar
						name={thread.userName || thread.userEmail}
						pictureUrl={null}
						userId={thread.userId}
						className="size-[26px]"
						fallbackClassName="text-[10px]"
					/>
					<div className="min-w-0">
						<p className="truncate text-[12.5px] font-medium text-foreground">
							{threadAuthor(thread)}
						</p>
						{thread.userName && thread.userEmail && (
							<p className="truncate text-[11px] text-meta dark:text-panel-dim">
								{thread.userEmail}
							</p>
						)}
					</div>
				</div>
			),
		},
		{
			key: "source",
			header: "Source",
			width: "100px",
			hideBelowLg: true,
			cell: (thread) => <ThreadSourceBadge source={thread.source} />,
		},
		{
			key: "created",
			header: "Created",
			width: "110px",
			mobileWidth: "auto",
			align: "right",
			cell: (thread) => (
				<time
					dateTime={thread.createdAt}
					title={formatDateTime(thread.createdAt)}
					className="whitespace-nowrap font-mono text-[11px] text-meta dark:text-panel-dim"
				>
					{formatDate(thread.createdAt)}
				</time>
			),
		},
	];

	return (
		<WorkspacePage
			slug="threads"
			parents={[
				{ label: "agents", href: "/agents" },
				{ label: agent?.name ?? "agent", href: `/agents/${agentId}` },
			]}
			title="Thread history"
			intro="Every conversation with this agent across the workspace, newest first."
			headerRight={
				agent && (
					<Link
						href={`/agents/${agentId}`}
						aria-label={`Back to ${agent.name}`}
						className="flex min-h-10 min-w-0 max-w-full items-center gap-2.5 rounded-[9px] border border-border bg-card px-3 py-1.5 transition-colors hover:border-border-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/35 dark:border-white/10 dark:bg-white/[0.03]"
					>
						<AgentAvatar
							agentId={agent.id}
							name={agent.name}
							imageRevision={agent.imageRevision}
							color={agent.color}
							emoji={agent.emoji}
							size="sm"
						/>
						<span className="min-w-0 truncate text-[13px] font-semibold text-foreground">
							{agent.name}
						</span>
					</Link>
				)
			}
		>
			<ForbiddenErrorDialog
				open={forbiddenOpen}
				onOpenChange={(open) => {
					setForbiddenOpen(open);
					if (!open) router.push(`/agents/${agentId}`);
				}}
				title="Insufficient privileges"
				message="You don't have permission to view this agent's threads."
			/>

			{loadError ? (
				<div
					role="alert"
					className="flex flex-wrap items-center gap-3 rounded-[9px] bg-destructive/10 px-3.5 py-2.5 text-[12.5px] font-medium text-destructive"
				>
					<span className="min-w-0 flex-1">{loadError}</span>
					<button
						type="button"
						onClick={() => {
							setReloadVersion((current) => current + 1);
						}}
						className="flex min-h-9 shrink-0 cursor-pointer items-center gap-1.5 rounded-[7px] px-2.5 font-semibold transition-colors hover:bg-destructive/10"
					>
						<RotateCcw className="size-3.5" />
						Retry
					</button>
				</div>
			) : (
				<DataTable
					columns={columns}
					rows={threads}
					rowKey={(thread) => thread.id}
					isLoading={isLoading}
					emptyMessage="No conversations with this agent yet."
					getRowHref={(thread) => `/agents/${agentId}/chat/${thread.id}`}
					pagination={{
						total,
						limit: PAGE_SIZE,
						offset,
						onOffsetChange: changePage,
						itemLabel: total === 1 ? "thread" : "threads",
					}}
				/>
			)}
		</WorkspacePage>
	);
}

"use client";

import { useDeferredValue, useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import {
	BulkConfirmDialog,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { BulkActionBar } from "@/components/ui/bulk-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import { ThreadSourceBadge } from "@/components/ui/thread-source-badge";
import { useRowSelection } from "@/hooks/use-row-selection";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as threadsApi from "@/lib/api/resources/threads";
import { useThreadsStore } from "@/stores/threads-store";
import type { Thread } from "@/types/threads";

const PAGE_SIZE = 20;

function formatDate(value: string): string {
	return new Date(value)
		.toLocaleDateString("en-US", {
			year: "numeric",
			month: "short",
			day: "numeric",
		})
		.toLowerCase();
}

function threadTitle(thread: Thread): string {
	return thread.firstMessageContent?.trim() || "Untitled conversation";
}

export default function ProfileThreads() {
	const router = useRouter();
	const removeStoredThread = useThreadsStore((state) => state.removeThread);
	const [threads, setThreads] = useState<Thread[]>([]);
	const [total, setTotal] = useState(0);
	const [offset, setOffset] = useState(0);
	const [search, setSearch] = useState("");
	const deferredSearch = useDeferredValue(search);
	const requestKey = `${offset}:${deferredSearch.trim()}`;
	const [settledRequestKey, setSettledRequestKey] = useState<string | null>(
		null,
	);
	const isLoading = settledRequestKey !== requestKey;
	const [loadError, setLoadError] = useState<string | null>(null);
	const [bulkOpen, setBulkOpen] = useState(false);

	useEffect(() => {
		let cancelled = false;
		void threadsApi
			.listThreads({
				limit: PAGE_SIZE,
				offset,
				q: deferredSearch.trim() || undefined,
			})
			.then((page) => {
				if (cancelled) return;
				setThreads(page.items);
				setTotal(page.total);
				setLoadError(null);
			})
			.catch((error: unknown) => {
				if (cancelled) return;
				setLoadError(getApiErrorMessage(error, "Could not load conversations."));
			})
			.finally(() => {
				if (!cancelled) setSettledRequestKey(requestKey);
			});
		return () => {
			cancelled = true;
		};
	}, [deferredSearch, offset, requestKey]);

	const selection = useRowSelection({
		orderedIds: threads.map((thread) => thread.id),
	});
	const selectedThreads = threads.filter((thread) =>
		selection.selectedIds.has(thread.id),
	);

	const columns: DataTableColumn<Thread>[] = [
		{
			key: "conversation",
			header: selection.selectionMode ? (
				""
			) : (
				<span className="flex items-center gap-3">
					<Checkbox
						checked={false}
						aria-label="Select all conversations"
						onCheckedChange={selection.toggleAll}
					/>
					<button
						type="button"
						onClick={selection.toggleAll}
						className="cursor-pointer text-[12px]! font-semibold text-foreground hover:text-petrol"
					>
						Select all
					</button>
				</span>
			),
			width: "minmax(280px, 1fr)",
			cell: (thread) => (
				<div className="flex min-w-0 items-center gap-3">
					<SelectableLeading
						selected={selection.isSelected(thread.id)}
						selectionMode={selection.selectionMode}
						label={`Select ${threadTitle(thread)}`}
						onToggle={(shiftKey) => {
							selection.toggle(thread.id, shiftKey);
						}}
						className="size-8"
					>
						<AgentAvatar
							agentId={thread.agentId}
							name={thread.agentName}
							imageRevision={thread.agentImageRevision}
							color={thread.agentColor}
							emoji={thread.agentEmoji}
							size="sm"
						/>
					</SelectableLeading>
					<div className="min-w-0">
						<p className="truncate text-[12.5px] font-semibold text-foreground">
							{threadTitle(thread)}
						</p>
						<p className="mt-0.5 truncate text-[11.5px] text-meta dark:text-panel-dim">
							{thread.agentArchived
								? "Archived agent"
								: thread.agentName || "Unknown agent"}
						</p>
					</div>
				</div>
			),
		},
		{
			key: "source",
			header: "Source",
			width: "100px",
			mobileWidth: "auto",
			cell: (thread) => <ThreadSourceBadge source={thread.source} />,
		},
		{
			key: "updated",
			header: "Created",
			width: "120px",
			mobileWidth: "auto",
			align: "right",
			cell: (thread) => (
				<span className="font-mono text-[11px] text-meta dark:text-panel-dim">
					{formatDate(thread.createdAt)}
				</span>
			),
		},
	];

	return (
		<div className="flex flex-col gap-3">
			<div className="mb-1">
				<span className="text-[10.5px] font-semibold text-subtle dark:text-panel-dim">
					Threads
				</span>
				<p className="mt-1.5 max-w-[620px] text-[13px] leading-[1.55] text-subtle dark:text-panel-body">
					Find and manage the conversations you started in this workspace.
				</p>
			</div>

			<div className="relative max-w-[420px]">
				<Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-meta" />
				<input
					type="search"
					value={search}
					placeholder="Search conversations or agents…"
					onChange={(event) => {
						setSearch(event.target.value);
						setOffset(0);
					}}
					className="h-9 w-full rounded-[9px] border border-border bg-card pl-9 pr-9 text-[12.5px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-ghost focus:border-petrol/55 focus:shadow-[0_0_0_3px_rgba(38,103,81,0.08)] dark:border-white/10"
				/>
				{search && (
					<button
						type="button"
						aria-label="Clear search"
						onClick={() => {
							setSearch("");
							setOffset(0);
						}}
						className="absolute right-2 top-1/2 flex size-6 -translate-y-1/2 cursor-pointer items-center justify-center rounded-[6px] text-meta transition-colors hover:bg-hover hover:text-foreground"
					>
						<X className="size-3.5" />
					</button>
				)}
			</div>

			{loadError && (
				<div className="rounded-[9px] bg-destructive/10 px-3.5 py-2.5 text-[12.5px] font-medium text-destructive">
					{loadError}
				</div>
			)}

			<BulkActionBar
				selectedCount={selection.selectedCount}
				totalCount={threads.length}
				allSelected={selection.allSelected}
				someSelected={selection.someSelected}
				onToggleAll={selection.toggleAll}
				onClear={selection.clear}
				actionLabel="Delete"
				onAction={() => {
					setBulkOpen(true);
				}}
			/>

			<DataTable
				columns={columns}
				rows={threads}
				rowKey={(thread) => thread.id}
				isLoading={isLoading}
				isRowSelected={(thread) => selection.isSelected(thread.id)}
				selectionMode={selection.selectionMode}
				onRowSelectionClick={(thread, shiftKey) => {
					selection.toggle(thread.id, shiftKey);
				}}
				minTableWidth="620px"
				onRowClick={(thread) => {
					router.push(`/agents/${thread.agentId}/chat/${thread.id}`);
				}}
				emptyMessage={
					deferredSearch ? "No conversation matches this search." : "No conversations yet."
				}
				pagination={{
					total,
					limit: PAGE_SIZE,
					offset,
					onOffsetChange: (nextOffset) => {
						setOffset(nextOffset);
					},
					itemLabel: total === 1 ? "thread" : "threads",
				}}
			/>

			<BulkConfirmDialog
				open={bulkOpen}
				onOpenChange={setBulkOpen}
				title="Delete selected conversations?"
				description="Their messages and run history will be removed permanently. This cannot be undone."
				items={selectedThreads.map((thread) => ({
					id: thread.id,
					name: threadTitle(thread),
					note: thread.agentName ? `Agent: ${thread.agentName}` : undefined,
				}))}
				confirmLabel="Delete"
				busyLabel="Deleting…"
				onConfirm={async (items) => {
					const results = await Promise.allSettled(
						items.map((item) => threadsApi.deleteThread(item.id)),
					);
					const succeeded: string[] = [];
					const failures: BulkFailure[] = [];
					results.forEach((result, index) => {
						const item = items.at(index);
						if (!item) return;
						if (result.status === "fulfilled") {
							succeeded.push(item.id);
							removeStoredThread(item.id);
						} else {
							failures.push({
								id: item.id,
								name: item.name,
								message: getApiErrorMessage(result.reason, "Delete failed."),
							});
						}
					});
					if (succeeded.length > 0) {
						const shouldGoBack =
							succeeded.length >= threads.length && offset > 0;
						const removed = new Set(succeeded);
						setThreads((current) =>
							current.filter((thread) => !removed.has(thread.id)),
						);
						setTotal((current) => Math.max(0, current - succeeded.length));
						selection.remove(succeeded);
						if (shouldGoBack) {
							setOffset((current) => Math.max(0, current - PAGE_SIZE));
						}
					}
					return failures;
				}}
			/>
		</div>
	);
}

"use client";

import { useDeferredValue, useEffect, useState } from "react";
import {
	AlarmClock,
	Braces,
	Circle,
	CircleCheck,
	Filter,
	Globe2,
	Layers3,
	ListChecks,
	Mail,
	MailOpen,
	MessageSquare,
	MoreHorizontal,
	Phone,
	RotateCcw,
	Search,
	Send,
	Trash2,
	X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { AgentAvatar } from "@/components/ui/agent-avatar";
import { ConversationCompletionButton } from "@/components/layout/app-sidebar/conversation-completion-button";
import {
	ThreadBulkMenu,
	toBulkThread,
} from "@/components/layout/app-sidebar/thread-bulk-menu";
import {
	BulkConfirmDialog,
	type BulkFailure,
} from "@/components/ui/bulk-confirm-dialog";
import { BulkActionBar } from "@/components/ui/bulk-action-bar";
import { Checkbox } from "@/components/ui/checkbox";
import { DataTable, type DataTableColumn } from "@/components/ui/data-table";
import { SelectableLeading } from "@/components/ui/selectable-leading";
import {
	SearchSelect,
	type SearchSelectOption,
} from "@/components/ui/search-select";
import { ThreadSourceBadge } from "@/components/ui/thread-source-badge";
import { ThreadUnreadBadge } from "@/components/ui/thread-unread-badge";
import { useQueryParamState } from "@/hooks/use-query-param-state";
import { useRowSelection } from "@/hooks/use-row-selection";
import { getApiErrorMessage } from "@/lib/api/errors";
import * as threadsApi from "@/lib/api/resources/threads";
import { useThreadsStore } from "@/stores/threads-store";
import { useUserStore } from "@/stores/user-store";
import { useWorkspaceEventsStore } from "@/stores/workspace-events-store";
import type { Thread, ThreadSource } from "@/types/threads";

const PAGE_SIZE = 20;
const READ_FILTERS = ["all", "read", "unread"] as const;
const COMPLETION_FILTERS = ["all", "completed", "uncompleted"] as const;
const READ_OPTIONS: SearchSelectOption[] = [
	{
		value: "all",
		label: "All read states",
		description: "Read and unread conversations",
		keywords: "any mixed",
		icon: <Layers3 />,
	},
	{
		value: "unread",
		label: "Unread",
		description: "Needs your attention",
		keywords: "new unseen",
		icon: <Mail />,
	},
	{
		value: "read",
		label: "Read",
		description: "Already seen",
		keywords: "seen opened",
		icon: <MailOpen />,
	},
];
const COMPLETION_OPTIONS: SearchSelectOption[] = [
	{
		value: "all",
		label: "All completion states",
		description: "Open and completed conversations",
		keywords: "any mixed",
		icon: <ListChecks />,
	},
	{
		value: "uncompleted",
		label: "Uncompleted",
		description: "Still active",
		keywords: "open active",
		icon: <Circle />,
	},
	{
		value: "completed",
		label: "Completed",
		description: "Finished conversations",
		keywords: "done closed",
		icon: <CircleCheck />,
	},
];
const SOURCE_OPTIONS: SearchSelectOption[] = [
	{
		value: "",
		label: "All sources",
		description: "Every conversation channel",
		keywords: "any mixed",
		icon: <Layers3 />,
	},
	{
		value: "web",
		label: "Web",
		description: "Conversations started in auxilia",
		icon: <Globe2 />,
	},
	{
		value: "slack",
		label: "Slack",
		description: "Slack conversations",
		icon: <MessageSquare />,
	},
	{
		value: "telegram",
		label: "Telegram",
		description: "Telegram conversations",
		icon: <Send />,
	},
	{
		value: "whatsapp",
		label: "WhatsApp",
		description: "WhatsApp conversations",
		icon: <Phone />,
	},
	{
		value: "api",
		label: "API",
		description: "Programmatic conversations",
		icon: <Braces />,
	},
	{
		value: "trigger",
		label: "Trigger",
		description: "Scheduled conversations",
		icon: <AlarmClock />,
	},
];

function localDateBoundary(value: string, nextDay = false): string | undefined {
	if (!value) return undefined;
	const date = new Date(`${value}T00:00:00`);
	if (Number.isNaN(date.getTime())) return undefined;
	if (nextDay) date.setDate(date.getDate() + 1);
	return date.toISOString();
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

function threadTitle(thread: Thread): string {
	return thread.firstMessageContent?.trim() || "Untitled conversation";
}

export default function ProfileThreads() {
	const router = useRouter();
	const canDeleteThreads = useUserStore(
		(state) => state.user?.canDeleteThreads === true,
	);
	const removeStoredThread = useThreadsStore((state) => state.removeThread);
	const setThreadCompleted = useThreadsStore(
		(state) => state.setThreadCompleted,
	);
	const setThreadReadState = useThreadsStore(
		(state) => state.setThreadReadState,
	);
	const threadsVersion = useWorkspaceEventsStore(
		(state) => state.threadsVersion,
	);
	const [threads, setThreads] = useState<Thread[]>([]);
	const [total, setTotal] = useState(0);
	const [search, setSearch] = useQueryParamState("threadQuery");
	const [readParam, setReadParam] = useQueryParamState("threadRead", "all");
	const [completionParam, setCompletionParam] = useQueryParamState(
		"threadCompletion",
		"all",
	);
	const [sourceParam, setSourceParam] = useQueryParamState("threadSource");
	const [createdFrom, setCreatedFrom] = useQueryParamState("threadFrom");
	const [createdTo, setCreatedTo] = useQueryParamState("threadTo");
	const [offsetParam, setOffsetParam] = useQueryParamState("threadOffset");
	const readStatus = READ_FILTERS.includes(
		readParam as (typeof READ_FILTERS)[number],
	)
		? (readParam as (typeof READ_FILTERS)[number])
		: "all";
	const completion = COMPLETION_FILTERS.includes(
		completionParam as (typeof COMPLETION_FILTERS)[number],
	)
		? (completionParam as (typeof COMPLETION_FILTERS)[number])
		: "all";
	const source = SOURCE_OPTIONS.some(
		(option) => option.value !== "" && option.value === sourceParam,
	)
		? (sourceParam as ThreadSource)
		: undefined;
	const parsedOffset = Number.parseInt(offsetParam, 10);
	const offset =
		Number.isFinite(parsedOffset) && parsedOffset >= 0 ? parsedOffset : 0;
	const deferredSearch = useDeferredValue(search);
	const [reloadVersion, setReloadVersion] = useState(0);
	const requestKey = [
		offset,
		deferredSearch.trim(),
		readStatus,
		completion,
		source ?? "",
		createdFrom,
		createdTo,
		threadsVersion,
		reloadVersion,
	].join(":");
	const [settledRequestKey, setSettledRequestKey] = useState<string | null>(
		null,
	);
	const isLoading = settledRequestKey !== requestKey;
	const [loadError, setLoadError] = useState<string | null>(null);
	const [bulkOpen, setBulkOpen] = useState(false);
	const [completionSavingIds, setCompletionSavingIds] = useState<Set<string>>(
		new Set(),
	);
	const [readSavingIds, setReadSavingIds] = useState<Set<string>>(new Set());
	const activeFilterCount = [
		search.trim(),
		readStatus !== "all" ? readStatus : "",
		completion !== "all" ? completion : "",
		source ?? "",
		createdFrom,
		createdTo,
	].filter(Boolean).length;

	const resetOffset = () => {
		setOffsetParam("");
	};

	useEffect(() => {
		let cancelled = false;
		void threadsApi
			.listThreads({
				limit: PAGE_SIZE,
				offset,
				q: deferredSearch.trim() || undefined,
				readStatus,
				completion,
				source,
				createdFrom: localDateBoundary(createdFrom),
				createdBefore: localDateBoundary(createdTo, true),
				includeApi: true,
			})
			.then((page) => {
				if (cancelled) return;
				setThreads(page.items);
				setTotal(page.total);
				setLoadError(null);
			})
			.catch((error: unknown) => {
				if (cancelled) return;
				setLoadError(
					getApiErrorMessage(error, "Could not load conversations."),
				);
			})
			.finally(() => {
				if (!cancelled) setSettledRequestKey(requestKey);
			});
		return () => {
			cancelled = true;
		};
	}, [
		completion,
		createdFrom,
		createdTo,
		deferredSearch,
		offset,
		readStatus,
		requestKey,
		source,
	]);

	const selection = useRowSelection({
		orderedIds: threads.map((thread) => thread.id),
	});
	const selectedThreads = threads.filter((thread) =>
		selection.selectedIds.has(thread.id),
	);
	const toggleCompletion = async (thread: Thread) => {
		if (completionSavingIds.has(thread.id)) return;
		setCompletionSavingIds((current) => new Set(current).add(thread.id));
		try {
			const updated = await setThreadCompleted(
				thread.id,
				thread.completedAt === null,
			);
			setThreads((current) =>
				current.map((item) => (item.id === thread.id ? updated : item)),
			);
			if (completion !== "all") {
				setReloadVersion((current) => current + 1);
			}
		} catch (error) {
			toast.error(
				getApiErrorMessage(error, "The conversation could not be updated."),
			);
		} finally {
			setCompletionSavingIds((current) => {
				const next = new Set(current);
				next.delete(thread.id);
				return next;
			});
		}
	};

	const toggleReadState = async (thread: Thread) => {
		if (readSavingIds.has(thread.id)) return;
		setReadSavingIds((current) => new Set(current).add(thread.id));
		setThreads((current) =>
			current.map((item) =>
				item.id === thread.id ? { ...item, isUnread: !thread.isUnread } : item,
			),
		);
		try {
			await setThreadReadState(thread.id, !thread.isUnread);
			if (readStatus !== "all") {
				setReloadVersion((current) => current + 1);
			}
		} catch (error) {
			setThreads((current) =>
				current.map((item) => (item.id === thread.id ? thread : item)),
			);
			toast.error(
				getApiErrorMessage(error, "The conversation could not be updated."),
			);
		} finally {
			setReadSavingIds((current) => {
				const next = new Set(current);
				next.delete(thread.id);
				return next;
			});
		}
	};

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
					<div className="min-w-0 flex-1">
						<div className="flex items-center gap-1.5">
							<p className="min-w-0 truncate text-[12.5px] font-semibold text-foreground">
								{threadTitle(thread)}
							</p>
							{thread.isUnread && <ThreadUnreadBadge />}
						</div>
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
		{
			key: "completed",
			header: "Complete",
			width: "76px",
			mobileWidth: "auto",
			align: "right",
			cell: (thread) => (
				<ConversationCompletionButton
					completed={thread.completedAt !== null}
					disabled={completionSavingIds.has(thread.id)}
					onToggle={() => {
						void toggleCompletion(thread);
					}}
					className="ml-auto"
				/>
			),
		},
		{
			key: "read",
			header: "Read",
			width: "64px",
			mobileWidth: "auto",
			align: "right",
			cell: (thread) =>
				thread.completedAt === null ? (
					<button
						type="button"
						aria-label={
							thread.isUnread
								? "Mark conversation as read"
								: "Mark conversation as unread"
						}
						title={thread.isUnread ? "Mark as read" : "Mark as unread"}
						disabled={readSavingIds.has(thread.id)}
						onClick={(event) => {
							event.preventDefault();
							event.stopPropagation();
							void toggleReadState(thread);
						}}
						className={`ml-auto flex size-7 cursor-pointer items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-petrol/40 disabled:cursor-wait disabled:opacity-50 ${
							thread.isUnread
								? "border-petrol/25 bg-petrol/8 text-petrol hover:bg-petrol/12 dark:border-panel-terminal/25 dark:bg-panel-terminal/10 dark:text-panel-terminal"
								: "border-border bg-card text-meta hover:bg-hover hover:text-foreground dark:bg-white/5"
						}`}
					>
						{thread.isUnread ? (
							<MailOpen className="size-3.5" />
						) : (
							<Mail className="size-3.5" />
						)}
					</button>
				) : null,
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

			<div className="flex flex-col gap-2 rounded-[11px] border border-border bg-sidebar/55 p-2 dark:border-white/10 dark:bg-white/[0.025]">
				<div className="flex flex-wrap items-center gap-2">
					<div className="flex h-8 shrink-0 items-center gap-1.5 px-1 text-[11px] font-semibold text-subtle">
						<Filter className="size-3.5" />
						<span>
							Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ""}
						</span>
					</div>
					<div className="relative min-w-[220px] flex-1">
						<Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-meta" />
						<input
							type="search"
							value={search}
							placeholder="Search conversations or agents…"
							onChange={(event) => {
								setSearch(event.target.value);
								resetOffset();
							}}
							className="h-8 w-full rounded-[8px] border border-border bg-card pl-9 pr-9 text-[12px] text-foreground outline-none transition-[border-color,box-shadow] placeholder:text-ghost focus:border-petrol/55 focus:shadow-[0_0_0_3px_rgba(38,103,81,0.08)] dark:border-white/10"
						/>
						{search && (
							<button
								type="button"
								aria-label="Clear search"
								onClick={() => {
									setSearch("");
									resetOffset();
								}}
								className="absolute right-1.5 top-1/2 flex size-6 -translate-y-1/2 cursor-pointer items-center justify-center rounded-[6px] text-meta transition-colors hover:bg-hover hover:text-foreground"
							>
								<X className="size-3.5" />
							</button>
						)}
					</div>
					<label className="flex h-8 items-center gap-1.5 rounded-[8px] border border-border bg-card px-2.5 text-[10.5px] text-meta dark:border-white/10">
						<span>From</span>
						<input
							type="date"
							value={createdFrom}
							onChange={(event) => {
								setCreatedFrom(event.target.value);
								resetOffset();
							}}
							className="min-w-0 bg-transparent font-mono text-[10.5px] text-foreground outline-none"
						/>
					</label>
					<label className="flex h-8 items-center gap-1.5 rounded-[8px] border border-border bg-card px-2.5 text-[10.5px] text-meta dark:border-white/10">
						<span>To</span>
						<input
							type="date"
							value={createdTo}
							onChange={(event) => {
								setCreatedTo(event.target.value);
								resetOffset();
							}}
							className="min-w-0 bg-transparent font-mono text-[10.5px] text-foreground outline-none"
						/>
					</label>
				</div>
				<div className="flex flex-wrap items-center gap-2 border-t border-border/70 pt-2 dark:border-white/8">
					<SearchSelect
						value={readStatus}
						options={READ_OPTIONS}
						ariaLabel="Read status"
						searchPlaceholder="Search read states…"
						active={readStatus !== "all"}
						onChange={(value) => {
							setReadParam(value);
							resetOffset();
						}}
					/>
					<SearchSelect
						value={completion}
						options={COMPLETION_OPTIONS}
						ariaLabel="Completion status"
						searchPlaceholder="Search completion states…"
						active={completion !== "all"}
						onChange={(value) => {
							setCompletionParam(value);
							resetOffset();
						}}
					/>
					<SearchSelect
						value={source ?? ""}
						options={SOURCE_OPTIONS}
						ariaLabel="Conversation source"
						searchPlaceholder="Search sources…"
						active={source !== undefined}
						onChange={(value) => {
							setSourceParam(value);
							resetOffset();
						}}
					/>
					{activeFilterCount > 0 && (
						<button
							type="button"
							onClick={() => {
								setSearch("");
								setReadParam("all");
								setCompletionParam("all");
								setSourceParam("");
								setCreatedFrom("");
								setCreatedTo("");
								resetOffset();
							}}
							className="ml-auto flex h-8 cursor-pointer items-center gap-1.5 rounded-[8px] px-2.5 text-[11.5px] font-semibold text-meta transition-colors hover:bg-hover hover:text-foreground"
						>
							<RotateCcw className="size-3.5" />
							Reset
						</button>
					)}
				</div>
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
				menu={
					selectedThreads.length > 0 && (
						<ThreadBulkMenu
							threads={selectedThreads.map(toBulkThread)}
							trigger={
								<button
									type="button"
									title="Bulk options"
									aria-label={`Bulk options for ${selectedThreads.length} selected conversation${
										selectedThreads.length === 1 ? "" : "s"
									}`}
									className="inline-flex size-[30px] cursor-pointer items-center justify-center rounded-[7px] border border-border bg-card text-foreground transition-[border-color,transform] hover:border-border-hover active:translate-y-px data-[state=open]:border-border-hover dark:border-white/10 dark:hover:border-white/20"
								>
									<MoreHorizontal className="size-3.5" />
								</button>
							}
							onUpdated={() => {
								setReloadVersion((current) => current + 1);
							}}
						/>
					)
				}
				actions={
					canDeleteThreads
						? [
								{
									label: "Delete",
									icon: <Trash2 className="size-3.5" />,
									destructive: true,
									onClick: () => {
										setBulkOpen(true);
									},
								},
							]
						: []
				}
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
					activeFilterCount > 0
						? "No conversation matches these filters."
						: "No conversations yet."
				}
				pagination={{
					total,
					limit: PAGE_SIZE,
					offset,
					onOffsetChange: (nextOffset) => {
						setOffsetParam(nextOffset > 0 ? String(nextOffset) : "");
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
							const previousOffset = Math.max(0, offset - PAGE_SIZE);
							setOffsetParam(previousOffset > 0 ? String(previousOffset) : "");
						}
					}
					return failures;
				}}
			/>
		</div>
	);
}

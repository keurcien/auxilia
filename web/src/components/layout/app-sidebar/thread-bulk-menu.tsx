"use client";

import { useState, type ReactNode } from "react";
import { CircleCheck, FolderInput, Mail, MailOpen, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { DropdownMenu } from "@/components/ui/dropdown-menu";
import {
	ThreadPlacementDialog,
	type ThreadPlacementTarget,
} from "@/components/layout/app-sidebar/thread-placement-dialog";
import { useProjectsStore } from "@/stores/projects-store";
import { useThreadsStore } from "@/stores/threads-store";
import type { Thread } from "@/types/threads";

/** What the bulk menu needs to know about one selected conversation. */
export interface BulkThread {
	id: string;
	title: string;
	completedAt: string | null;
	isUnread: boolean;
	projectId: string | null;
	folderId: string | null;
	canComplete: boolean;
	canMove: boolean;
}

/** A conversation from the viewer's own thread list: every action applies. */
export function toBulkThread(thread: Thread): BulkThread {
	return {
		id: thread.id,
		title: thread.firstMessageContent?.trim() || "Untitled conversation",
		completedAt: thread.completedAt ?? null,
		isUnread: thread.isUnread === true,
		projectId: thread.projectId ?? null,
		folderId: thread.folderId ?? null,
		canComplete: true,
		canMove: true,
	};
}

/**
 * Overflow menu for a selection of conversations: read state, completion
 * and project placement. Each entry only targets the threads it changes.
 */
export function ThreadBulkMenu({
	threads,
	trigger,
	onUpdated,
	disabled = false,
	align = "end",
	side = "bottom",
}: {
	threads: BulkThread[];
	trigger: ReactNode;
	/** Called after any bulk change, so a list can refetch or prune. */
	onUpdated?: () => void;
	disabled?: boolean;
	align?: "start" | "end";
	side?: "bottom" | "right" | "left" | "top";
}) {
	const setThreadCompleted = useThreadsStore(
		(state) => state.setThreadCompleted,
	);
	const setThreadReadState = useThreadsStore(
		(state) => state.setThreadReadState,
	);
	const refreshTree = useProjectsStore((state) => state.refreshTree);
	const [moveTargets, setMoveTargets] = useState<ThreadPlacementTarget[] | null>(
		null,
	);
	const [busy, setBusy] = useState(false);

	const run = async (
		targets: BulkThread[],
		update: (thread: BulkThread) => Promise<unknown>,
	) => {
		setBusy(true);
		try {
			const results = await Promise.allSettled(targets.map(update));
			const failed = results.filter(
				(result) => result.status === "rejected",
			).length;
			if (failed > 0) {
				toast.error(
					failed === targets.length
						? "The conversations could not be updated."
						: `${failed} of ${targets.length} conversations could not be updated.`,
				);
			}
			void refreshTree();
			onUpdated?.();
		} finally {
			setBusy(false);
		}
	};

	const withCount = (label: string, count: number) =>
		count === threads.length ? label : `${label} (${count})`;
	// Completed conversations have no read state.
	const open = threads.filter((thread) => thread.completedAt === null);
	const toMarkRead = open.filter((thread) => thread.isUnread);
	const toMarkUnread = open.filter((thread) => !thread.isUnread);
	const toComplete = open.filter((thread) => thread.canComplete);
	const toReopen = threads.filter(
		(thread) => thread.completedAt !== null && thread.canComplete,
	);
	const toMove = threads.filter((thread) => thread.canMove);

	const stateItems = [
		...(toMarkRead.length > 0
			? [
					{
						label: withCount("Mark as read", toMarkRead.length),
						icon: <MailOpen />,
						onClick: () => {
							void run(toMarkRead, (thread) =>
								setThreadReadState(thread.id, false),
							);
						},
					},
				]
			: []),
		...(toMarkUnread.length > 0
			? [
					{
						label: withCount("Mark as unread", toMarkUnread.length),
						icon: <Mail />,
						onClick: () => {
							void run(toMarkUnread, (thread) =>
								setThreadReadState(thread.id, true),
							);
						},
					},
				]
			: []),
		...(toComplete.length > 0
			? [
					{
						label: withCount("Mark as complete", toComplete.length),
						icon: <CircleCheck />,
						onClick: () => {
							void run(toComplete, (thread) =>
								setThreadCompleted(thread.id, true),
							);
						},
					},
				]
			: []),
		...(toReopen.length > 0
			? [
					{
						label: withCount("Reopen", toReopen.length),
						icon: <Undo2 />,
						onClick: () => {
							void run(toReopen, (thread) =>
								setThreadCompleted(thread.id, false),
							);
						},
					},
				]
			: []),
	];
	const items = [
		...stateItems,
		...(toMove.length > 0
			? [
					...(stateItems.length > 0 ? [{ separator: true as const }] : []),
					{
						label: withCount("Move to project…", toMove.length),
						icon: <FolderInput />,
						onClick: () => {
							setMoveTargets(
								toMove.map((thread) => ({
									id: thread.id,
									title: thread.title,
									projectId: thread.projectId,
									folderId: thread.folderId,
								})),
							);
						},
					},
				]
			: []),
	];

	if (items.length === 0) return null;

	return (
		<>
			{disabled || busy ? (
				<span className="pointer-events-none opacity-50">{trigger}</span>
			) : (
				<DropdownMenu
					trigger={trigger}
					align={align}
					side={side}
					items={items}
				/>
			)}
			<ThreadPlacementDialog
				open={moveTargets !== null}
				onOpenChange={(nextOpen) => {
					if (!nextOpen) setMoveTargets(null);
				}}
				threads={moveTargets ?? []}
				onMoved={onUpdated}
			/>
		</>
	);
}
